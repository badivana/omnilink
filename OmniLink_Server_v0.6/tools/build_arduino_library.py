"""Package OmniLink_Arduino_v0.3 as an Arduino IDE library ZIP (root folder "OmniLink").

Install the result with Sketch -> Include Library -> Add .ZIP Library.
Credentials and build output are never included.
"""
import argparse
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LIBRARY=ROOT.parent/'OmniLink_Arduino_v0.3'   # separate package next to the server, like the web client
SKIP_NAMES={'device-credentials.json','.DS_Store'}
SKIP_SUFFIXES={'.pyc','.exe','.o','.bin','.key'}

def build(destination):
    destination=Path(destination).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
    files=[p for p in sorted(LIBRARY.rglob('*')) if p.is_file() and not p.is_symlink()
           and p.name not in SKIP_NAMES and p.suffix not in SKIP_SUFFIXES and '__pycache__' not in p.parts]
    if not files:raise SystemExit(f'{LIBRARY} not found or empty; nothing to package.')
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in files: archive.write(path,'OmniLink/'+path.relative_to(LIBRARY).as_posix())
    with zipfile.ZipFile(destination) as archive: assert archive.testzip() is None
    print(f'{destination}: {len(files)} files')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('destination',nargs='?',default=str(ROOT.parent/'OmniLink_Arduino_v0.3.zip'))
    build(parser.parse_args().destination)
