"""Read-only dependency inventory from common manifests (no network, no installs)."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path


def list_dependencies(root: Path) -> dict:
    groups = []
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text())
            for section in ("dependencies", "devDependencies"):
                deps = data.get(section) or {}
                if deps:
                    groups.append({"manager": "npm", "manifest": "package.json", "section": section,
                                   "items": [{"name": k, "version": str(v)} for k, v in sorted(deps.items())][:500]})
        except (OSError, ValueError):
            pass
    for name, manager, sections in (("Cargo.toml", "cargo", ("dependencies", "dev-dependencies")), ("pyproject.toml", "python", ())):
        path = root / name
        if not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if manager == "cargo":
            for section in sections:
                deps = data.get(section) or {}
                if deps:
                    groups.append({"manager": "cargo", "manifest": name, "section": section,
                                   "items": [{"name": k, "version": v if isinstance(v, str) else str(v.get("version", v.get("path", "workspace")))} for k, v in sorted(deps.items())][:500]})
        else:
            deps = (data.get("project") or {}).get("dependencies") or []
            if deps:
                groups.append({"manager": "python", "manifest": name, "section": "dependencies",
                               "items": [{"name": d.split(">")[0].split("=")[0].split("<")[0].split("[")[0].strip(), "version": d} for d in deps][:500]})
    return {"groups": groups}
