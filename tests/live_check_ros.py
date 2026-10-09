"""Actual integration check: all point data must come from the running VGGT worker."""
import argparse,json,subprocess,time
from pathlib import Path
import numpy as np
import rosbag,rospy
from sensor_msgs.msg import PointCloud2

p=argparse.ArgumentParser();p.add_argument('--bridge',type=Path,required=True);p.add_argument('--frames',type=int,default=2)
p.add_argument('--bag',type=Path,default=Path('/demo/data/nuplan_front_2hz.bag'))
a=p.parse_args();processes=[];received=[];root=Path('/demo')
try:
    master_log=(a.bridge/'master.log').open('w')
    processes.append(subprocess.Popen(['roscore'],stdout=master_log,stderr=subprocess.STDOUT))
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        if processes[0].poll() is not None:raise RuntimeError('roscore failed: see master.log')
        try:
            if rospy.get_master().getPid()[0]==1:break
        except Exception:pass
        time.sleep(.2)
    else:raise RuntimeError('Master startup timeout')
    rospy.init_node('vggt_live_verifier',anonymous=True)
    rospy.set_param('/use_sim_time',True)
    sub=rospy.Subscriber('/vggt/points',PointCloud2,received.append,queue_size=1)
    processes.append(subprocess.Popen(['rosrun','vggt_scene','scene_node.py','_frames:='+str(a.frames),'_bridge:='+str(a.bridge)]))
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        _,_,state=rospy.get_master().getSystemState()
        if any(t=='/camera/front/image_raw/compressed' and ns for t,ns in state[1]):break
        time.sleep(.2)
    else:raise RuntimeError('Camera subscriber not registered')
    start=time.monotonic()
    processes.append(subprocess.Popen(['rosbag','play','--clock','--duration='+str(a.frames*.5+.1),str(a.bag)],stdout=subprocess.DEVNULL))
    deadline=time.monotonic()+1800
    while time.monotonic()<deadline and not received:
        errors=list(a.bridge.glob('*/error.json'))
        if errors:raise RuntimeError(errors[0].read_text())
        time.sleep(.2)
    assert received,'Timed out waiting for the real VGGT cloud'
    msg=received[0]
    jobs=list(a.bridge.glob('*/result.npz'));assert len(jobs)==1
    job=jobs[0].parent
    with np.load(str(jobs[0]),allow_pickle=False) as data:
        xyz=data['xyz'];rgb=data['rgb']
        points=np.frombuffer(msg.data,dtype=[('x','<f4'),('y','<f4'),('z','<f4'),('rgba','<u4')])
        np.testing.assert_array_equal(np.column_stack([points[x] for x in ('x','y','z')]),xyz)
        rgba=(255<<24)|(rgb[:,0].astype('uint32')<<16)|(rgb[:,1].astype('uint32')<<8)|rgb[:,2]
        np.testing.assert_array_equal(points['rgba'],rgba)
        assert len(xyz)>1000 and np.isfinite(xyz).all()
        bounds=[xyz.min(0).tolist(),xyz.max(0).tolist()]
    request=json.loads((job/'request.json').read_text())
    assert msg.header.stamp.to_nsec()==request['frames'][-1]['stamp_ns']
    assert msg.header.frame_id=='vggt_world'
    with rosbag.Bag(str(a.bridge/'published_cloud.bag'),'w') as bag:bag.write('/vggt/points',msg,msg.header.stamp)
    report=dict(passed=True,model_inference_tested=True,fixture=False,frames=a.frames,points=msg.width,
                topic='/vggt/points',frame_id=msg.header.frame_id,xyz_rgb_exact_match=True,
                seconds_bag_to_cloud=time.monotonic()-start,bounds_arbitrary_units=bounds,job=job.name)
    (a.bridge/'ros_verified.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)
finally:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
