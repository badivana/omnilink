"""Package source and docs; never include installed dependencies or live data."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TOP={'Dockerfile','LICENSE','README.md','VALIDATION.md','compose.yaml','pytest.ini',
     'requirements.txt','requirements-dev.txt','run.bat','run.sh','setup.bat','setup.sh',
     'deploy-vps.sh','compose.mqtt-plain.yaml','.dockerignore','.gitignore'}
FOLDERS={'omnilink','examples','tests','deploy','docs','tools'}

def build(destination):
    destination=Path(destination).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
    files=[]
    for path in ROOT.rglob('*'):
        if not path.is_file() or path.is_symlink(): continue
        rel=path.relative_to(ROOT)
        if any(part in ('__pycache__','.pytest_cache','.venv','data') for part in rel.parts): continue
        if rel.parts[0] not in FOLDERS and str(rel) not in TOP: continue
        if path.suffix in ('.pyc','.db','.key') or path.name=='.env' or path.name=='device-credentials.json': continue
        files.append((rel,path.read_bytes()))
    digest='\n'.join(hashlib.sha256(data).hexdigest()+'  '+str(rel).replace('\\','/') for rel,data in sorted(files))+'\n'
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for rel,data in sorted(files): archive.writestr('OmniLink_Server_v0.6/'+str(rel).replace('\\','/'),data)
        archive.writestr('OmniLink_Server_v0.6/MANIFEST_SHA256.txt',digest)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
    print(f'{destination}: {len(files)+1} files, {destination.stat().st_size} bytes')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination',nargs='?',default=str(ROOT.parent/'OmniLink_Server_v0.6.zip'))
    build(parser.parse_args().destination)
