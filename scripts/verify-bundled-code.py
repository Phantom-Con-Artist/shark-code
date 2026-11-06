"""Compare trusted PyInstaller Python modules with current source before releasing a sidecar."""
import argparse
import types
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def normalize(code):
    return code.replace(co_filename='', co_consts=tuple(normalize(c) if isinstance(c, types.CodeType) else c for c in code.co_consts))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary',type=Path)
    args=parser.parse_args()
    archive=CArchiveReader(str(args.binary))
    name=next(name for name in archive.toc if name.endswith('.pyz'))
    python=archive.open_embedded_archive(name)
    root=Path(__file__).resolve().parents[1]/'backend'
    mismatches=[]
    checked=0
    for path in sorted((root/'shark_runtime').rglob('*.py')):
        if path.name=='frozen.py':
            continue  # Entry scripts are stored separately in the executable archive.
        module='.'.join(path.relative_to(root).with_suffix('').parts)
        if module.endswith('.__init__'):
            module=module.removesuffix('.__init__')
        bundled=python.extract(module)
        current=compile(path.read_bytes(),str(path),'exec',dont_inherit=True,optimize=0)
        if not isinstance(bundled,types.CodeType) or normalize(bundled)!=normalize(current):
            mismatches.append(module)
        checked+=1
    bundled=archive.extract('frozen')
    if bundled is not None:
        import marshal
        current=compile((root/'shark_runtime/frozen.py').read_bytes(),'frozen.py','exec',dont_inherit=True,optimize=0)
        if normalize(marshal.loads(bundled))!=normalize(current):
            mismatches.append('frozen')
    if mismatches:
        raise SystemExit('Bundled modules differ from current source: '+', '.join(mismatches))
    print(f'Verified {checked} bundled runtime modules against current source')


if __name__=='__main__':
    main()
