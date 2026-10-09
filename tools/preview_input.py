"""Display the real image sequence in Rerun, independently of VGGT readiness."""
import argparse,json,subprocess,sys
from pathlib import Path
import rerun as rr
import rerun.blueprint as rrb

p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--no-viewer',action='store_true')
a=p.parse_args();root=Path(__file__).resolve().parents[1]
manifest=json.loads((a.source/'manifest.json').read_text())
out=root/'outputs/nuplan_input_2hz.rrd'
rr.init('nuplan_input_2hz')
rr.save(str(out))
rr.send_blueprint(rrb.Blueprint(rrb.Spatial2DView(origin='camera',name='nuPlan CAM_F0 — input images, not reconstruction')))
for i,frame in enumerate(sorted(manifest['frames'],key=lambda f:f['timestamp'])):
    rr.set_time('frame',sequence=i)
    rr.set_time('time',duration=i*.5)
    rr.log('camera',rr.EncodedImage(path=a.source/frame['file']))
rr.get_global_data_recording().flush(blocking=True);rr.disconnect()
print(out)
if not a.no_viewer: subprocess.Popen([sys.executable,'-m','rerun',str(out)])
