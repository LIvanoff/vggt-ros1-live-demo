"""VGGT-1B: CPU FP32/INT8 or experimental CUDA FP32/BF16/FP16."""
from pathlib import Path
import time
import numpy as np
from PIL import Image

def prepare_images(paths,width=280):
    if width<140 or width%14: raise ValueError('width must be a multiple of 14 and >=140')
    images=[]
    for path in paths:
        with Image.open(path) as image:
            height=max(14,round(image.height*width/image.width/14)*14)
            images.append(np.asarray(image.convert('RGB').resize((width,height),Image.Resampling.BICUBIC)))
    if len({x.shape for x in images})!=1: raise ValueError('Images must have the same aspect ratio')
    return np.stack(images)

def select_points(points,confidence,colors,depth,quantile=.6,max_points=80000):
    valid=np.isfinite(points).all(axis=-1)&np.isfinite(confidence)&np.isfinite(depth)&(depth>0)
    # Simple sky suppression for this road sequence, not semantic segmentation.
    valid[:,:int(points.shape[1]*.24),:]=False
    if not valid.any(): raise ValueError('No finite positive-depth points')
    threshold=float(np.quantile(confidence[valid],quantile))
    keep=valid&(confidence>=threshold)
    xyz=points[keep].astype(np.float32);rgb=colors[keep].astype(np.uint8)
    if len(xyz)>max_points:
        indices=np.linspace(0,len(xyz)-1,max_points,dtype=int)
        xyz,rgb=xyz[indices],rgb[indices]
    return xyz,rgb,threshold

class Reconstructor:
    def __init__(self,weights,source,width=280,threads=4,min_free_ram_gib=7,precision='fp32',device='cpu'):
        import sys,psutil
        import torch
        allowed={'cpu':{'fp32','int8'},'cuda':{'fp32','bf16','fp16'}}
        if device not in allowed or precision not in allowed[device]:
            raise ValueError('Supported: CPU fp32/int8; CUDA fp32/bf16/fp16')
        if device=='cuda':
            if not torch.cuda.is_available():
                raise RuntimeError('CUDA unavailable: check NVIDIA PyTorch, driver and container GPU access')
            if precision=='bf16' and not torch.cuda.is_bf16_supported():
                raise RuntimeError('This CUDA device does not support BF16; select --precision fp16')
        available=psutil.virtual_memory().available
        if available < min_free_ram_gib*1024**3:
            raise RuntimeError('Only %.2f GiB RAM available; configured preflight requires %.2f GiB. No model was loaded.' % (available/1024**3,min_free_ram_gib))
        print('Loading VGGT on %s (%s); available RAM %.2f GiB' % (device,precision,available/1024**3),flush=True)
        sys.path.insert(0,str(Path(source).resolve()))
        from accelerate import init_empty_weights
        from safetensors import safe_open
        from vggt.models.vggt import VGGT
        torch.set_num_threads(threads)
        torch.set_num_interop_threads(1)
        # Avoid allocating random 1B-parameter weights before loading the checkpoint.
        with init_empty_weights():
            model=VGGT(enable_point=False,enable_track=False)
        expected_shapes={k:tuple(v.shape) for k,v in model.state_dict().items()}
        keys=set(expected_shapes)
        if precision=='int8':
            # On Windows, mapping the whole safetensors file can reserve its
            # entire size against the commit limit. Read individual tensors instead.
            import json,math,struct
            with open(weights,'rb') as stream:
                header_length=struct.unpack('<Q',stream.read(8))[0]
                if header_length>16*1024**2:raise ValueError('Unexpected checkpoint header size')
                header=json.loads(stream.read(header_length))
            missing=keys-set(header)
            if missing:raise RuntimeError('Checkpoint is missing keys: '+str(sorted(missing)[:5]))
            def read_tensor(key):
                entry=header[key]
                if tuple(entry['shape'])!=expected_shapes[key]:raise ValueError('Unexpected tensor shape: '+key)
                dtypes={'F32':'<f4','F64':'<f8','F16':'<f2','I64':'<i8','I32':'<i4','BOOL':'?'}
                dtype=np.dtype(dtypes[entry['dtype']]);count=math.prod(entry['shape'])
                lo,hi=entry['data_offsets']
                if hi-lo!=count*dtype.itemsize:raise ValueError('Invalid tensor size: '+key)
                with open(weights,'rb') as stream:
                    stream.seek(8+header_length+lo)
                    array=np.fromfile(stream,dtype=dtype,count=count)
                if array.size!=count:raise ValueError('Truncated tensor: '+key)
                return torch.from_numpy(array.reshape(entry['shape']))
            linear_layers=[(name,module) for name,module in model.named_modules() if isinstance(module,torch.nn.Linear)]
            linear_keys=set()
            for i,(name,module) in enumerate(linear_layers):
                names=['weight']+(['bias'] if module.bias is not None else [])
                linear_keys.update(name+'.'+key for key in names)
                state={key:read_tensor(name+'.'+key) for key in names}
                module.load_state_dict(state,strict=True,assign=True)
                module.qconfig=torch.ao.quantization.default_dynamic_qconfig
                quantized=torch.ao.nn.quantized.dynamic.Linear.from_float(module)
                parent,_,leaf=name.rpartition('.')
                setattr(model.get_submodule(parent),leaf,quantized)
                # The iteration list still references module; release FP32 data.
                module.weight=torch.nn.Parameter(torch.empty(0,device='meta'),requires_grad=False)
                module.bias=None
                del state
                if (i+1)%50==0 or i+1==len(linear_layers):
                    print('INT8 linear layers: %d/%d'%(i+1,len(linear_layers)),flush=True)
            for key in keys-linear_keys:
                parent,_,leaf=key.rpartition('.')
                module=model.get_submodule(parent)
                value=read_tensor(key)
                if leaf in module._parameters:
                    value=torch.nn.Parameter(value,requires_grad=False)
                setattr(module,leaf,value)
        elif precision in ('fp32','bf16','fp16'):
            with safe_open(str(weights),framework='pt',device='cpu') as f:
                missing=keys-set(f.keys())
                if missing: raise RuntimeError('Checkpoint is missing keys: '+str(sorted(missing)[:5]))
                state={k:f.get_tensor(k) for k in keys}
            model.load_state_dict(state,strict=True,assign=True)
        self.model=model.eval()
        self.device=device
        if device=='cuda':self.model=self.model.to(device)
        self.width=width
        self.precision=precision

    def run(self,paths):
        import torch
        from vggt.utils.pose_enc import pose_encoding_to_extri_intri
        from vggt.utils.geometry import unproject_depth_map_to_point_map
        rgb=prepare_images(paths,self.width)
        images=torch.from_numpy(rgb.copy()).permute(0,3,1,2).float().div_(255).to(self.device)
        if self.device=='cuda':torch.cuda.synchronize()
        start=time.perf_counter()
        from contextlib import nullcontext
        mixed=self.device=='cuda' and self.precision in ('bf16','fp16')
        context=torch.autocast('cuda',dtype=torch.bfloat16 if self.precision=='bf16' else torch.float16) if mixed else nullcontext()
        with torch.inference_mode(), context:
            result=self.model(images)
            extrinsic,intrinsic=pose_encoding_to_extri_intri(result['pose_enc'],images.shape[-2:])
        if self.device=='cuda':torch.cuda.synchronize()
        depth=result['depth'][0].float().cpu().numpy()
        confidence=result['depth_conf'][0].float().cpu().numpy()
        extrinsic=extrinsic[0].float().cpu().numpy();intrinsic=intrinsic[0].float().cpu().numpy()
        points=unproject_depth_map_to_point_map(depth,extrinsic,intrinsic)
        xyz,colors,threshold=select_points(points,confidence,rgb,depth[...,0])
        return dict(xyz=xyz,rgb=colors,images=rgb,depth=depth[...,0],extrinsic=extrinsic,
                    intrinsic=intrinsic,seconds=np.asarray(time.perf_counter()-start),
                    confidence_threshold=np.asarray(threshold),precision=np.asarray(self.precision),device=np.asarray(self.device))
