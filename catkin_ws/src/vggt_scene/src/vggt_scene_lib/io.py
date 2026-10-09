#!/usr/bin/env python3
"""Provided infrastructure: local file bridge and a PointCloud2 serializer."""
import hashlib
import json
import time
import uuid
from pathlib import Path
import numpy as np
import rospy
from sensor_msgs.msg import PointCloud2, PointField
from std_msgs.msg import Header

def reconstruct(frames, bridge_dir, timeout=1800):
    job = Path(bridge_dir) / uuid.uuid4().hex
    job.mkdir(parents=True)
    rows=[]
    for i,msg in enumerate(frames):
        name='frame_%03d.jpg' % i
        (job/name).write_bytes(msg.data)
        rows.append(dict(file=name,seq=msg.header.seq,stamp_ns=msg.header.stamp.to_nsec(),
                         sha256=hashlib.sha256(msg.data).hexdigest()))
    pending=job/'request.tmp'
    pending.write_text(json.dumps(dict(schema=1,frames=rows)),encoding='utf8')
    pending.replace(job/'request.json')  # The worker sees only a complete request.
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline and not rospy.is_shutdown():
        if (job/'error.json').exists():
            raise RuntimeError(json.loads((job/'error.json').read_text())['error'])
        if (job/'result.npz').exists():
            with np.load(str(job/'result.npz'),allow_pickle=False) as data:
                return {k:data[k].copy() for k in data.files}
        time.sleep(.2)  # Wall time: simulation time can stop when the bag finishes.
    raise TimeoutError('VGGT worker timeout; see the worker terminal: '+str(job))

def cloud_message(xyz,rgb,stamp):
    xyz=np.asarray(xyz,dtype=np.float32)
    rgb=np.asarray(rgb,dtype=np.uint8)
    assert xyz.ndim==2 and xyz.shape[1]==3 and rgb.shape==xyz.shape
    keep=np.isfinite(xyz).all(axis=1)
    xyz,rgb=xyz[keep],rgb[keep]
    packed=np.empty(len(xyz),dtype=[('x','<f4'),('y','<f4'),('z','<f4'),('rgba','<u4')])
    for j,k in enumerate(('x','y','z')): packed[k]=xyz[:,j]
    packed['rgba']=(255<<24)|(rgb[:,0].astype('uint32')<<16)|(rgb[:,1].astype('uint32')<<8)|rgb[:,2]
    msg=PointCloud2(header=Header(stamp=stamp,frame_id='vggt_world'))
    msg.height=1;msg.width=len(xyz)
    msg.fields=[PointField(k,j*4,PointField.FLOAT32,1) for j,k in enumerate(('x','y','z'))]
    msg.fields.append(PointField('rgba',12,PointField.UINT32,1))
    msg.is_bigendian=False;msg.point_step=16;msg.row_step=16*len(xyz)
    msg.is_dense=True;msg.data=packed.tobytes()
    return msg
