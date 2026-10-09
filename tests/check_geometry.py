"""Check coordinate direction and model construction without claiming inference."""
import argparse,json,sys
from pathlib import Path
import numpy as np
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=root/'external/vggt');a=p.parse_args()
sys.path[:0]=[str(a.source),str(root/'worker')]
(root/'outputs').mkdir(exist_ok=True)
from vggt.utils.geometry import unproject_depth_map_to_point_map
from inference import select_points
depth=np.full((1,2,2,1),2,dtype=np.float32)
E=np.array([[[1,0,0,1],[0,1,0,0],[0,0,1,0]]],dtype=np.float32)
K=np.eye(3,dtype=np.float32)[None]
points=unproject_depth_map_to_point_map(depth,E,K)
np.testing.assert_allclose(points[0,0,0],[-1,0,2])
np.testing.assert_allclose(points[0,1,1],[1,2,2])
confidence=np.ones((1,2,2),dtype=np.float32)
colors=np.full((1,2,2,3),127,dtype=np.uint8)
points[0,1,1]=np.nan
xyz,rgb,threshold=select_points(points,confidence,colors,depth[...,0])
assert len(xyz)==3 and np.isfinite(xyz).all() and rgb.dtype==np.uint8
from accelerate import init_empty_weights
from vggt.models.vggt import VGGT
with init_empty_weights(): model=VGGT(enable_point=False,enable_track=False)
assert all(p.device.type=='meta' for p in model.parameters())
report=dict(passed=True,scope='camera-to-world inversion, positive-depth/finite point selection, empty model initialization',
            instantiated_parameters=sum(p.numel() for p in model.parameters()),model_inference_tested=False)
checkpoint=root/'models/model.safetensors'
if checkpoint.is_file():
    from safetensors import safe_open
    with safe_open(str(checkpoint),framework='pt',device='cpu') as saved:
        state=model.state_dict()
        missing=set(state)-set(saved.keys())
        assert not missing,sorted(missing)
        mismatches=[k for k,v in state.items() if tuple(saved.get_slice(k).get_shape())!=tuple(v.shape)]
        assert not mismatches,mismatches
    report.update(checkpoint_keys_and_shapes_verified=True,verified_state_entries=len(state))
(root/'outputs/geometry_check.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
