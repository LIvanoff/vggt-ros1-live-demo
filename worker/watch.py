"""Consume complete ROS jobs from a shared directory, run VGGT, return NPZ."""
import argparse,hashlib,json,time,traceback
from pathlib import Path
import numpy as np
from inference import Reconstructor
from viewer import log_reconstruction

def run():
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser()
    p.add_argument('--bridge',type=Path,default=root/'bridge')
    p.add_argument('--weights',type=Path,default=root/'models/model.safetensors')
    p.add_argument('--source',type=Path,default=root/'external/vggt')
    p.add_argument('--width',type=int,default=280)
    p.add_argument('--threads',type=int,default=4)
    p.add_argument('--min-free-ram-gib',type=float,default=3)
    p.add_argument('--precision',choices=['fp32','int8','bf16','fp16'],default='int8')
    p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    p.add_argument('--no-viewer',action='store_true')
    p.add_argument('--once',action='store_true')
    a=p.parse_args()
    if not a.weights.is_file(): p.error('Download models/model.safetensors with tools/download_model.py first')
    if a.min_free_ram_gib < 2: p.error('Preflight threshold must be at least 2 GiB; use the monitored rehearsal for constrained-memory tests')
    engine=Reconstructor(a.weights,a.source,a.width,a.threads,a.min_free_ram_gib,a.precision,a.device)
    print('VGGT loaded on',a.device,'; waiting for a ROS job in',a.bridge,flush=True)
    a.bridge.mkdir(parents=True,exist_ok=True)
    (a.bridge/'worker_ready.json').write_text(json.dumps(dict(device=a.device,precision=a.precision,width=a.width,threads=a.threads)))
    while True:
        for request in sorted(a.bridge.glob('*/request.json')):
            job=request.parent
            if any((job/n).exists() for n in ('result.npz','error.json')): continue
            try:
                data=json.loads(request.read_text())
                assert data['schema']==1 and 2<=len(data['frames'])<=8
                paths=[]
                for frame in data['frames']:
                    assert Path(frame['file']).name==frame['file']
                    path=job/frame['file']
                    assert hashlib.sha256(path.read_bytes()).hexdigest()==frame['sha256']
                    paths.append(path)
                print('Reconstructing',len(paths),'frames at width',a.width,flush=True)
                result=engine.run(paths)
                output=root/'outputs'/('scene_'+job.name+'.rrd')
                output.parent.mkdir(exist_ok=True)
                log_reconstruction(result,job.name,output,not a.no_viewer)
                with (job/'result.tmp').open('wb') as f: np.savez_compressed(f,**result)
                (job/'result.tmp').replace(job/'result.npz')
                report=dict(frames=len(paths),width=a.width,seconds=float(result['seconds']),
                            points=len(result['xyz']),viewer=str(output),device=a.device,cached=False,precision=a.precision,
                            frame_stamps_ns=[f['stamp_ns'] for f in data['frames']])
                (job/'report.json').write_text(json.dumps(report,indent=2))
                print(json.dumps(report,indent=2),flush=True)
            except Exception as exc:
                (job/'error.json').write_text(json.dumps(dict(error=str(exc))))
                traceback.print_exc()
                if a.once: raise
            if a.once:return
        time.sleep(.2)

if __name__=='__main__': run()
