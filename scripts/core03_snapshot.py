'''Verify frozen inputs used by the additive Core 0.3 projection.'''
from hashlib import file_digest,sha256
import json
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
LOCK='source/core03-frozen-inputs.json'
def manifest_binding(root=ROOT):
    raw=(root/'bundle/data/manifest.json').read_bytes()
    return {'path':'data/manifest.json','sha256':sha256(raw).hexdigest(),'bytes':len(raw),'okf_version':json.loads(raw)['okf_version'],'source_commit':json.loads((root/LOCK).read_bytes())['source_commit']}
def verify_frozen_inputs(root=ROOT):
    lock=json.loads((root/LOCK).read_bytes())
    if lock.get('schema')!='okf-legislation-core03-frozen-inputs.v1' or lock.get('source_okf_version')!='0.2':
        raise ValueError('Unknown frozen source lock')
    seen=set()
    for row in lock['files']:
        relative=PurePosixPath(row['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix() in seen:
            raise ValueError('Unsafe or duplicate frozen input path')
        seen.add(relative.as_posix());path=root/relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Frozen input escapes the repository')
        with path.open('rb')as stream:digest=file_digest(stream,'sha256').hexdigest()
        if digest!=row['sha256'] or path.stat().st_size!=row['bytes']:
            raise ValueError('Frozen input changed: '+str(relative))
    if 'bundle/data/manifest.json'not in seen or manifest_binding(root)['okf_version']!='0.2':
        raise ValueError('The accepted Core 0.2 source manifest must be preserved')
    return {'files':len(seen),'source_manifest':manifest_binding(root)}
if __name__=='__main__':print(json.dumps(verify_frozen_inputs(),sort_keys=True))
