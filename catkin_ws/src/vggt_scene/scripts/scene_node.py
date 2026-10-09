#!/usr/bin/env python3
"""The node to write live. Heavy model/visualization code is provided separately."""
import threading
import rospy
from sensor_msgs.msg import CompressedImage, PointCloud2
from vggt_scene_lib.io import reconstruct, cloud_message

class SceneNode:
    def __init__(self):
        self.count=int(rospy.get_param('~frames',2))
        self.stride=int(rospy.get_param('~stride',1))
        self.bridge=rospy.get_param('~bridge','/demo/bridge')
        if not 2<=self.count<=8 or self.stride<1:
            raise ValueError('frames must be 2..8, stride must be positive')
        self.frames=[]
        self.seen=0
        self.started=False
        self.lock=threading.Lock()
        self.pub=rospy.Publisher('/vggt/points',PointCloud2,queue_size=1,latch=True)
        self.sub=rospy.Subscriber('/camera/front/image_raw/compressed',CompressedImage,
                                  self.on_image,queue_size=10,buff_size=16*1024*1024)
        rospy.loginfo('Waiting for %d images; play the 2 Hz bag',self.count)

    def on_image(self,msg):
        with self.lock:
            if self.started: return
            take=(self.seen % self.stride==0)
            self.seen+=1
            if not take: return
            self.frames.append(msg)
            rospy.loginfo('Collected %d/%d: seq=%d',len(self.frames),self.count,msg.header.seq)
            if len(self.frames)==self.count:
                self.started=True
                # Never run slow inference while holding up the ROS subscriber.
                threading.Thread(target=self.run_inference,daemon=True).start()

    def run_inference(self):
        try:
            result=reconstruct(self.frames,self.bridge)
            cloud=cloud_message(result['xyz'],result['rgb'],self.frames[-1].header.stamp)
            self.pub.publish(cloud)
            rospy.loginfo('Published %d points in vggt_world (unknown metric scale)',cloud.width)
        except Exception as exc:
            rospy.logerr('Reconstruction failed: %s',exc)

if __name__=='__main__':
    rospy.init_node('vggt_scene')
    node=SceneNode()
    rospy.spin()
