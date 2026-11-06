"""Content-addressed build directories prevent reuse after source changes during a build."""
import hashlib
from pathlib import Path

root=Path(__file__).resolve().parents[1]
paths=list((root/'backend/shark_runtime').rglob('*.py'))
paths += [root/'backend/pyproject.toml',root/'backend/uv.lock',root/'scripts/build-sidecars.sh',
          root/'scripts/verify-bundled-code.py',root/'scripts/runtime-build-key.py']
digest=hashlib.sha256()
for path in sorted(paths):
    digest.update(path.relative_to(root).as_posix().encode()+b'\0')
    digest.update(hashlib.sha256(path.read_bytes()).digest())
print(digest.hexdigest()[:24])
