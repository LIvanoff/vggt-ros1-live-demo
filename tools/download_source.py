"""Fetch only official VGGT Python sources, not the large example image archive."""
import base64,concurrent.futures,hashlib,json,urllib.request
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]/'external/vggt'
REV='a288dd0f14786c93483e45524328726ab7b1b4ce'
api='https://api.github.com/repos/facebookresearch/vggt/git/trees/'+REV+'?recursive=1'
with urllib.request.urlopen(api,timeout=45) as response:tree=json.load(response)['tree']
paths=[x['path'] for x in tree if x['type']=='blob' and
       ((x['path'].startswith('vggt/') and x['path'].endswith('.py')) or x['path'] in ['LICENSE.txt','README.md','requirements.txt'])]
hashes={x['path']:x['sha'] for x in tree if x['type']=='blob'}
def blob_hash(content):
    return hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
def fetch(path):
    parts=PurePosixPath(path).parts
    assert '..' not in parts and not path.startswith('/')
    target=ROOT.joinpath(*parts);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and blob_hash(target.read_bytes())==hashes[path]: return path
    url='https://raw.githubusercontent.com/facebookresearch/vggt/'+REV+'/'+path
    try:
        with urllib.request.urlopen(url,timeout=30) as r:content=r.read()
    except Exception:
        with urllib.request.urlopen('https://api.github.com/repos/facebookresearch/vggt/git/blobs/'+hashes[path],timeout=30) as r:
            content=base64.b64decode(json.load(r)['content'])
    assert blob_hash(content)==hashes[path],path
    target.write_bytes(content)
    return path
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    done=list(pool.map(fetch,paths))
(ROOT/'SOURCE.json').write_text(json.dumps(dict(repo='facebookresearch/vggt',commit=REV,files=done),indent=2))
print('Downloaded',len(done),'official source files at',REV)
