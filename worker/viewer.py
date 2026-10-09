"""Save RRD and optionally launch a native Rerun viewer on the worker host."""
import numpy as np

def log_reconstruction(result,recording_id,output,spawn=True):
    import rerun as rr
    import rerun.blueprint as rrb
    rr.init('nuplan_vggt_ros1',recording_id=recording_id)
    # Open the recording before logging. It can be reused at class without inference.
    rr.save(str(output))
    rr.log('world',rr.ViewCoordinates.RDF,static=True)
    rr.log('world/points',rr.Points3D(result['xyz'],colors=result['rgb']),static=True)
    centers=[]
    for i,(E,K,image,depth) in enumerate(zip(result['extrinsic'],result['intrinsic'],result['images'],result['depth'])):
        # VGGT E maps world -> camera. Rerun Transform3D maps child -> parent.
        R=E[:3,:3].T
        center=-R@E[:3,3]
        centers.append(center)
        path='world/camera_%02d'%i
        rr.log(path,rr.Transform3D(translation=center,mat3x3=R),static=True)
        rr.log(path+'/image',rr.Pinhole(image_from_camera=K,resolution=[image.shape[1],image.shape[0]]),static=True)
        rr.log(path+'/image',rr.Image(image),static=True)
        rr.set_time('frame',sequence=i)
        rr.log('input/image',rr.Image(image))
        # Do not claim metres for monocular VGGT output.
        rr.log('input/depth_relative',rr.Tensor(depth))
    rr.log('world/camera_path',rr.LineStrips3D([np.asarray(centers)],colors=[255,180,40]),static=True)
    rr.log('info',rr.TextDocument('VGGT-1B, device: %s, precision: %s. Independent reconstruction of this image batch.\nUnknown metric scale. Not nuPlan ground truth, not a fused map or SLAM.\nInference time: %.2f s'%(str(result.get('device','cpu')),str(result.get('precision','fp32')),float(result['seconds']))),static=True)
    blueprint=rrb.Blueprint(rrb.Horizontal(rrb.Spatial3DView(origin='world',name='VGGT scene'),
                  rrb.Vertical(rrb.Spatial2DView(origin='input/image',name='Input'),rrb.TextDocumentView(origin='info'))))
    rr.send_blueprint(blueprint)
    rr.get_global_data_recording().flush(blocking=True)
    rr.disconnect()
    if spawn:
        # CLI opens the completed recording, avoiding a Linux GUI and port forwarding.
        import subprocess,sys
        subprocess.Popen([sys.executable,'-m','rerun',str(output)])
