"""Download one safetensors checkpoint, with disk guard and SHA-256 verification."""
from pathlib import Path
import hashlib,json,shutil,time,urllib.request

ROOT=Path(__file__).resolve().parents[1]
target=ROOT/'models/model.safetensors'
target.parent.mkdir(exist_ok=True)
REV='860abec7937da0a4c03c41d3c269c366e82abdf9'
meta_url='https://huggingface.co/api/models/facebook/VGGT-1B/revision/'+REV+'?blobs=true'
with urllib.request.urlopen(meta_url,timeout=45) as r: meta=json.load(r)
item=next(x for x in meta['siblings'] if x['rfilename']=='model.safetensors')
size=item['size'];expected=item['lfs']['sha256'];revision=meta['sha']
part=target.with_suffix('.part')
existing=part.stat().st_size if part.exists() else 0
if target.exists(): existing=target.stat().st_size
required=max(0,size-existing)+2*1024**3
if shutil.disk_usage(target.parent).free<required:
    raise SystemExit('Insufficient space: need remaining checkpoint bytes plus 2 GiB free reserve')
if not target.exists():
    url='https://huggingface.co/facebook/VGGT-1B/resolve/'+revision+'/model.safetensors'
    headers={'User-Agent':'mirea-vggt-class/1.0'}
    if existing: headers['Range']='bytes=%d-'%existing
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=60) as response:
        append=existing and response.status==206
        if append and not response.headers.get('Content-Range','').startswith('bytes %d-'%existing):
            raise RuntimeError('Server returned an unexpected range')
        received=existing if append else 0
        last=time.monotonic()
        with part.open('ab' if append else 'wb') as f:
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                f.write(chunk);received+=len(chunk)
                if time.monotonic()-last>10:
                    print('Downloaded %.1f / %.1f MB'%(received/1e6,size/1e6),flush=True);last=time.monotonic()
    if part.stat().st_size!=size: raise RuntimeError('Incomplete download; run again to resume')
    candidate=part
else: candidate=target
digest=hashlib.sha256()
with candidate.open('rb') as f:
    while True:
        chunk=f.read(8*1024*1024)
        if not chunk:break
        digest.update(chunk)
if digest.hexdigest()!=expected: raise RuntimeError('Checkpoint checksum mismatch')
if candidate==part: part.replace(target)
(target.parent/'checkpoint.json').write_text(json.dumps(dict(repo='facebook/VGGT-1B',revision=revision,size=size,sha256=expected),indent=2))
print('Verified',target,flush=True)
