"""Host runner: real VGGT process plus actual ROS bag/node in Docker."""
import argparse,datetime,json,os,subprocess,sys,time
from pathlib import Path
import psutil
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--frames',type=int,default=2);p.add_argument('--width',type=int,default=280)
p.add_argument('--min-free-ram-gib',type=float,default=3)
p.add_argument('--precision',choices=['fp32','int8','bf16','fp16'],default='int8')
p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
p.add_argument('--weights',type=Path,default=root/'models/model.safetensors')
p.add_argument('--source',type=Path,default=root/'external/vggt')
p.add_argument('--bag',type=Path,default=root/'data/nuplan_front_2hz.bag')
p.add_argument('--image',default='vggt-ros1:noetic-v1')
a=p.parse_args()
if not a.bag.is_file():p.error('Missing bag: copy it into data/ or pass --bag PATH')
if not 2<=a.frames<=8:p.error('Frames must be 2..8')
(root/'bridge').mkdir(exist_ok=True)
(root/'outputs').mkdir(exist_ok=True)
tag=datetime.datetime.now().strftime('rehearsal_%Y%m%d_%H%M%S')
bridge=root/'bridge'/tag;bridge.mkdir()
worker_log=(bridge/'worker.log').open('w',encoding='utf8');ros_log=(bridge/'ros.log').open('w',encoding='utf8')
worker=subprocess.Popen([sys.executable,'-X','utf8','-u',str(root/'worker/watch.py'),'--bridge',str(bridge),'--width',str(a.width),'--min-free-ram-gib',str(a.min_free_ram_gib),'--precision',a.precision,'--device',a.device,'--weights',str(a.weights.resolve()),'--source',str(a.source.resolve()),'--once','--no-viewer'],stdout=worker_log,stderr=subprocess.STDOUT)
ros=None;peak=0;minimum_available=psutil.virtual_memory().available
container_name='vggt-'+tag.lower().replace('_','-')
user_args=['--user',str(os.getuid())+':'+str(os.getgid())] if hasattr(os,'getuid') else []
def sample_memory():
    global peak,minimum_available
    available=psutil.virtual_memory().available
    minimum_available=min(minimum_available,available)
    if available<512*1024**2:
        raise RuntimeError('Stopped rehearsal: system available RAM fell below 512 MiB')
    try:
        parent=psutil.Process(worker.pid)
        processes=[parent]+parent.children(recursive=True)
    except psutil.NoSuchProcess:return
    rss=0
    for process in processes:
        try:rss+=process.memory_info().rss
        except psutil.NoSuchProcess:pass
    peak=max(peak,rss)
print('Rehearsal directory:',bridge,flush=True)
try:
    start=time.monotonic();deadline=start+300
    while not (bridge/'worker_ready.json').exists():
        if worker.poll() is not None:raise RuntimeError('Worker failed: '+(bridge/'worker.log').read_text(encoding='utf8'))
        if time.monotonic()>deadline:raise RuntimeError('VGGT load timeout')
        sample_memory();time.sleep(.5)
    print('Weights loaded; starting real ROS playback',flush=True)
    command='source /opt/ros/noetic/setup.bash && cd /demo/catkin_ws && catkin_make && source devel/setup.bash && python3 /demo/tests/live_check_ros.py --frames '+str(a.frames)+' --bag /input.bag --bridge /demo/bridge/'+tag
    ros=subprocess.Popen(['docker','run','--rm','--name',container_name,*user_args,'--network','none','-e','HOME=/tmp','-e','ROS_HOSTNAME=localhost','-e','ROS_MASTER_URI=http://localhost:11311','--mount','type=bind,source='+str(root)+',target=/demo','--mount','type=bind,source='+str(a.bag.resolve())+',target=/input.bag,readonly',a.image,'bash','-lc',command],stdout=ros_log,stderr=subprocess.STDOUT)
    while ros.poll() is None:
        if worker.poll() is None:sample_memory()
        elif worker.returncode:raise RuntimeError('Worker failed: '+(bridge/'worker.log').read_text(encoding='utf8'))
        if time.monotonic()-start>1900:raise RuntimeError('Rehearsal deadline exceeded')
        time.sleep(.5)
    if ros.returncode:raise RuntimeError('ROS verification failed: '+(bridge/'ros.log').read_text(encoding='utf8'))
    worker.wait(timeout=30)
    assert worker.returncode==0
    report=json.loads((bridge/'ros_verified.json').read_text())
    report.update(worker_peak_rss_bytes=peak,system_min_available_bytes=minimum_available,total_seconds=time.monotonic()-start,width=a.width,bridge=str(bridge),checked_at=datetime.datetime.now().astimezone().isoformat())
    report.update(json.loads(next(bridge.glob('*/report.json')).read_text()))
    (root/'outputs/live_rehearsal.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)
except Exception as exc:
    failure=dict(passed=False,error=str(exc),bridge=str(bridge),frames=a.frames,width=a.width,precision=a.precision,
                 available_ram_bytes=psutil.virtual_memory().available,worker_peak_rss_bytes=peak,system_min_available_bytes=minimum_available,
                 checked_at=datetime.datetime.now().astimezone().isoformat())
    (root/'outputs/live_rehearsal_failed.json').write_text(json.dumps(failure,indent=2),encoding='utf8')
    raise
finally:
    if ros is not None and ros.poll() is None:
        subprocess.run(['docker','stop','--time','2',container_name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
        ros.wait(timeout=15)
    if worker.poll() is None:
        try:
            owned=psutil.Process(worker.pid)
            descendants=owned.children(recursive=True)
            for child in descendants:
                try:child.terminate()
                except psutil.NoSuchProcess:pass
            owned.terminate()
            psutil.wait_procs(descendants+[owned],timeout=5)
        except psutil.NoSuchProcess:pass
    worker_log.close();ros_log.close()
