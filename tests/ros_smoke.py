"""Integration test of real bag -> node -> file bridge -> PointCloud2.

The worker response is an explicit test fixture, NOT a VGGT prediction.
The test never writes to the normal bridge or visualization output folders.
"""
import json,os,subprocess,sys,tempfile,time
from pathlib import Path
import numpy as np
import rospy
from sensor_msgs.msg import PointCloud2
import sensor_msgs.point_cloud2 as pc2

root=Path('/demo');processes=[]
with tempfile.TemporaryDirectory(prefix='vggt_transport_test_') as tmp:
    bridge=Path(tmp)
    try:
        processes.append(subprocess.Popen(['roscore'],stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT))
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            try: rospy.get_master().getPid();break
            except Exception:time.sleep(.2)
        rospy.init_node('test_vggt_transport',anonymous=True)
        received=[]
        sub=rospy.Subscriber('/vggt/points',PointCloud2,received.append)
        processes.append(subprocess.Popen(['rosrun','vggt_scene','scene_node.py','_frames:=2','_bridge:='+str(bridge)]))
        # Wait for subscription registration; the bag remains unchanged.
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            _,_,state=rospy.get_master().getSystemState()
            if any(t=='/camera/front/image_raw/compressed' and ns for t,ns in state[1]):break
            time.sleep(.2)
        else:raise AssertionError('No camera subscriber')
        processes.append(subprocess.Popen(['rosbag','play','--duration=1.1',str(root/'data/nuplan_front_2hz.bag')],stdout=subprocess.DEVNULL))
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            jobs=list(bridge.glob('*/request.json'))
            if jobs:break
            time.sleep(.1)
        else:raise AssertionError('No bridge request')
        job=jobs[0].parent;request=json.loads(jobs[0].read_text())
        assert len(request['frames'])==2
        assert request['frames'][1]['stamp_ns']-request['frames'][0]['stamp_ns']==500000000
        assert all((job/f['file']).stat().st_size>100000 for f in request['frames'])
        fixture=dict(xyz=np.array([[1,2,3],[4,5,6],[np.nan,0,0]],np.float32),rgb=np.array([[255,0,0],[0,255,0],[0,0,255]],np.uint8))
        with (job/'result.tmp').open('wb') as f:np.savez(f,**fixture)
        (job/'result.tmp').replace(job/'result.npz')
        deadline=time.monotonic()+10
        while not received and time.monotonic()<deadline:time.sleep(.1)
        assert received,'No output cloud'
        msg=received[0];rows=list(pc2.read_points(msg,field_names=['x','y','z','rgba']))
        assert msg.width==2 and msg.header.frame_id=='vggt_world'
        assert msg.header.stamp.to_nsec()==request['frames'][-1]['stamp_ns']
        assert rows[0]==(1.,2.,3.,0xffff0000) and rows[1]==(4.,5.,6.,0xff00ff00)
        report=dict(passed=True,scope='ROS transport, JPEG bridge, timestamps, XYZ/RGBA serialization and NaN filtering',
                    model_inference_tested=False,input_messages=2,output_points=2)
        (root/'outputs/ros_smoke.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
    finally:
        for process in reversed(processes):
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
