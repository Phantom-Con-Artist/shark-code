"""Manifest and lockfile facts. No package installation or executable project config."""
from __future__ import annotations

import json
import hashlib
import re
import tomllib
from collections import defaultdict
from pathlib import PurePosixPath


def inventory(sources: dict[str, str]) -> dict:
    declarations, packages, edges, errors, licenses = [], [], [], [], []
    def declared(path, ecosystem, name, requirement, section):
        declarations.append({'path': path, 'ecosystem': ecosystem, 'name': name, 'requirement': str(requirement), 'section': section})
    for path, text in sorted(sources.items()):
        filename = PurePosixPath(path).name
        if filename not in {'package.json', 'package-lock.json', 'Cargo.toml', 'Cargo.lock', 'pyproject.toml', 'uv.lock', 'poetry.lock', 'go.mod', 'go.sum', 'requirements.txt'}:
            continue
        try:
            if filename == 'package.json':
                doc = json.loads(text)
                for section in ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'):
                    for name, requirement in (doc.get(section) or {}).items():
                        declared(path, 'npm', name, requirement, section)
                if doc.get('license'):
                    licenses.append({'path': path, 'name': doc.get('name'), 'license': doc['license'], 'evidence': 'manifest'})
            elif filename == 'package-lock.json':
                doc = json.loads(text)
                locked = doc.get('packages', {})
                ids = {}
                for location, pkg in locked.items():
                    if not location or pkg.get('link'):
                        continue
                    name = pkg.get('name') or location.rsplit('node_modules/', 1)[-1]
                    identity = f'{path}:{location}'
                    ids[location] = identity
                    packages.append({'id': identity, 'ecosystem': 'npm', 'name': name, 'version': pkg.get('version'),
                                     'path': path, 'location': location, 'license': pkg.get('license'),
                                     'source': _safe_url(pkg.get('resolved')), 'integrity_present': bool(pkg.get('integrity'))})
                for location, pkg in locked.items():
                    for name in (pkg.get('dependencies') or {}):
                        target = _npm_resolve(location, name, ids)
                        edges.append({'source': ids.get(location, f'{path}:root'), 'target': target,
                                      'name': name, 'resolution': 'lockfile' if target else 'unresolved'})
                if not locked and doc.get('dependencies'):
                    errors.append({'path': path, 'reason': 'npm v1 lockfile is not supported; upgrade or provide a v2/v3 lockfile'})
            elif filename in {'Cargo.toml', 'pyproject.toml'}:
                doc = tomllib.loads(text)
                if filename == 'Cargo.toml':
                    sections = [(s, doc.get(s, {})) for s in ('dependencies', 'dev-dependencies', 'build-dependencies')]
                    sections += [(f'target.{target}.{s}', table.get(s, {})) for target, table in doc.get('target', {}).items()
                                 for s in ('dependencies', 'dev-dependencies', 'build-dependencies')]
                    for section, items in sections:
                        for name, value in items.items():
                            actual = value.get('package', name) if isinstance(value, dict) else name
                            requirement = value.get('version', 'workspace' if value.get('workspace') else 'path/git') if isinstance(value, dict) else value
                            declared(path, 'crates.io', actual, requirement, section)
                    pkg = doc.get('package', {})
                    if pkg.get('license'):
                        licenses.append({'path': path, 'name': pkg.get('name'), 'license': pkg['license'], 'evidence': 'manifest'})
                else:
                    for requirement in doc.get('project', {}).get('dependencies', []):
                        name = re.match(r'[\w.-]+', requirement)
                        if name:
                            declared(path, 'PyPI', name[0], requirement, 'dependencies')
                    for section, items in doc.get('project', {}).get('optional-dependencies', {}).items():
                        for requirement in items:
                            name = re.match(r'[\w.-]+', requirement)
                            if name:
                                declared(path, 'PyPI', name[0], requirement, f'optional.{section}')
            elif filename in {'Cargo.lock', 'uv.lock', 'poetry.lock'}:
                doc = tomllib.loads(text)
                ecosystem = 'crates.io' if filename == 'Cargo.lock' else 'PyPI'
                rows = doc.get('package', [])
                lookup = defaultdict(list)
                for pkg in rows:
                    identity = _locked_id(path, pkg)
                    source = pkg.get('source')
                    packages.append({'id': identity, 'ecosystem': ecosystem, 'name': pkg['name'], 'version': pkg.get('version'),
                                     'path': path, 'source': _safe_url(source) if isinstance(source, str) else _safe_source(source),
                                     'license': None, 'integrity_present': bool(pkg.get('checksum') or pkg.get('sdist', {}).get('hash'))})
                    lookup[pkg['name']].append((pkg.get('version'), identity))
                for pkg in rows:
                    source = _locked_id(path, pkg)
                    deps = pkg.get('dependencies', [])
                    for dep in deps:
                        if isinstance(dep, str):
                            parts = dep.split()
                            name, version = parts[0], parts[1] if len(parts) > 1 else None
                        elif isinstance(dep, dict):
                            name, version = dep['name'], dep.get('version')
                        else:
                            continue
                        candidates = [identity for ver, identity in lookup.get(name, []) if version is None or ver == version]
                        edges.append({'source': source, 'target': candidates[0] if len(candidates) == 1 else None,
                                      'name': name, 'resolution': 'lockfile' if len(candidates) == 1 else 'unresolved'})
            elif filename == 'go.mod':
                in_require = False
                for line in text.splitlines():
                    line = line.split('//', 1)[0].strip()
                    if line == 'require (':
                        in_require = True
                    elif line == ')':
                        in_require = False
                    elif line.startswith('require ') or in_require:
                        parts = line.removeprefix('require ').split()
                        if len(parts) >= 2:
                            declared(path, 'Go', parts[0], parts[1], 'require')
            elif filename == 'requirements.txt':
                for line in text.splitlines():
                    name = re.match(r'([\w.-]+)(?:\[[^]]+\])?\s*([<>=!~].*)?$', line.strip())
                    if name and not line.lstrip().startswith('#'):
                        declared(path, 'PyPI', name[1], name[0], 'requirements')
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            errors.append({'path': path, 'reason': f'Invalid manifest: {type(exc).__name__}'})
    versions = defaultdict(set)
    for pkg in packages:
        if pkg['version']:
            versions[(pkg['ecosystem'], pkg['name'])].add(pkg['version'])
    multiple = [{'ecosystem': e, 'name': n, 'versions': sorted(v), 'interpretation': 'multiple versions; not proof of incompatibility'}
                for (e, n), v in sorted(versions.items()) if len(v) > 1]
    return {'declarations': declarations, 'packages': packages, 'edges': edges, 'multiple_versions': multiple,
            'licenses': licenses, 'errors': errors, 'methodology': 'manifest-lockfile-v1',
            'limitations': ['Only recorded manifests and supported lockfiles are examined.',
                            'Missing license metadata is unknown, not an unrestricted license.',
                            'Version ranges and runtime compatibility are not proven by inventory.']}


def _npm_resolve(location, name, ids):
    current = location
    while True:
        candidate = f'{current}/node_modules/{name}' if current else f'node_modules/{name}'
        if candidate in ids:
            return ids[candidate]
        if not current:
            return None
        current = current.rsplit('/node_modules/', 1)[0] if '/node_modules/' in current else ''


def _safe_url(value):
    if not value or not isinstance(value, str):
        return None
    from urllib.parse import urlsplit, urlunsplit
    try:
        parsed = urlsplit(value)
        if parsed.scheme and parsed.netloc:
            host = parsed.hostname or ''
            if parsed.port:
                host += f':{parsed.port}'
            return urlunsplit((parsed.scheme, host, parsed.path, '', ''))[:500]
        return value.split('?', 1)[0].split('#', 1)[0][:500]
    except ValueError:
        return '[invalid source]'


def _safe_source(value):
    return {key: _safe_url(val) for key, val in (value or {}).items() if isinstance(val, str)} if isinstance(value, dict) else None


def _locked_id(path, package):
    provenance = hashlib.sha256(json.dumps(package.get('source'), sort_keys=True).encode()).hexdigest()[:12]
    return f"{path}:{package['name']}@{package.get('version', 'local')}:{provenance}"
