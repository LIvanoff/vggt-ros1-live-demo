#!/usr/bin/env python3
"""Run with ROS 1 Python. Preserve JPEG bytes; use an exact 2 Hz teaching timeline."""
import argparse
import hashlib
import json
from pathlib import Path
import rosbag
import rospy
from sensor_msgs.msg import CompressedImage

TOPIC = '/camera/front/image_raw/compressed'

def main():
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--hz', type=float, default=2.0)
    args = p.parse_args()
    assert args.hz > 0
    manifest = json.loads((args.source / 'manifest.json').read_text())
    frames = sorted(manifest['frames'], key=lambda f: f['timestamp'])
    assert len(frames) == manifest['frame_count']
    assert all(a['timestamp'] < b['timestamp'] for a,b in zip(frames, frames[1:]))
    start_ns = frames[0]['timestamp'] * 1000
    step_ns = round(1e9 / args.hz)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists(): raise FileExistsError(args.output)
    rows=[]
    with rosbag.Bag(str(args.output), 'w') as bag:
        for i,frame in enumerate(frames):
            file = args.source / frame['file']
            payload = file.read_bytes()
            stamp_ns = start_ns + i * step_ns
            msg = CompressedImage()
            msg.header.seq = i
            msg.header.stamp = rospy.Time(stamp_ns // 10**9, stamp_ns % 10**9)
            msg.header.frame_id = 'cam_front_optical'
            msg.format = 'jpeg'
            msg.data = payload
            bag.write(TOPIC, msg, t=msg.header.stamp)
            rows.append(dict(seq=i,file=file.name,source_timestamp_us=frame['timestamp'],
                             bag_timestamp_ns=stamp_ns,sha256=hashlib.sha256(payload).hexdigest()))
    # Check the file actually written, rather than just the producer's counters.
    with rosbag.Bag(str(args.output)) as bag:
        loaded=list(bag.read_messages(topics=[TOPIC]))
        assert len(loaded)==len(rows)
        for (topic,msg,t),row in zip(loaded,rows):
            assert t.to_nsec()==msg.header.stamp.to_nsec()==row['bag_timestamp_ns']
            assert hashlib.sha256(msg.data).hexdigest()==row['sha256']
    report=dict(scene=manifest['scene_name'],messages=len(rows),topic=TOPIC,hz=args.hz,
                duration_seconds=(len(rows)-1)/args.hz,stamp_policy='regularized_2hz_from_first_source_timestamp',
                calibration='not present in input; CameraInfo/TF are not fabricated',frames=rows)
    args.output.with_suffix('.manifest.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='frames'},indent=2))

if __name__=='__main__': main()
