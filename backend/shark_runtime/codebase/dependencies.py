"""Manifest, lockfile, alias, compatibility, advisory, license, and SBOM intelligence."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tomllib
from collections import defaultdict
from pathlib import PurePosixPath
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

PERMISSIVE_LICENSES = {
    'MIT', 'APACHE-2.0', 'APACHE 2.0', 'BSD-2-CLAUSE', 'BSD-3-CLAUSE', 'BSD',
    'ISC', '0BSD', 'UNLICENSE', 'ZLIB', 'CC0-1.0', 'PYTHON-2.0', 'ARTISTIC-2.0',
    'BLUEOAK-1.0.0', 'MIT OR APACHE-2.0', 'APACHE-2.0 OR MIT', 'MIT/APACHE-2.0',
}
WEAK_COPYLEFT_LICENSES = {
    'LGPL-2.1', 'LGPL-2.1-ONLY', 'LGPL-2.1-OR-LATER', 'LGPL-3.0', 'LGPL-3.0-ONLY',
    'LGPL-3.0-OR-LATER', 'MPL-2.0', 'EPL-1.0', 'EPL-2.0', 'CDDL-1.0',
}
STRONG_COPYLEFT_LICENSES = {
    'GPL-2.0', 'GPL-2.0-ONLY', 'GPL-2.0-OR-LATER', 'GPL-3.0', 'GPL-3.0-ONLY',
    'GPL-3.0-OR-LATER', 'AGPL-3.0', 'AGPL-3.0-ONLY', 'AGPL-3.0-OR-LATER', 'SSPL-1.0',
}

PYPI_IMPORT_ALIASES = {
    'beautifulsoup4': {'bs4'},
    'pillow': {'pil'},
    'pyyaml': {'yaml'},
    'scikit-learn': {'sklearn'},
    'opencv-python': {'cv2'},
    'pyjwt': {'jwt'},
    'python-dotenv': {'dotenv'},
    'python-dateutil': {'dateutil'},
    'attrs': {'attr', 'attrs'},
    'ast-grep-py': {'ast_grep_py'},
    'docstring-parser': {'docstring_parser'},
    'tree-sitter-language-pack': {'tree_sitter_language_pack'},
}

PYTHON_STDLIB = set(getattr(sys, 'stdlib_module_names', ())) | {
    '__future__', 'abc', 'argparse', 'ast', 'asyncio', 'base64', 'bisect', 'builtins',
    'collections', 'concurrent', 'contextlib', 'contextvars', 'copy', 'csv', 'ctypes',
    'dataclasses', 'datetime', 'decimal', 'difflib', 'dis', 'email', 'enum', 'errno',
    'Empty', 'faulthandler', 'fcntl', 'filecmp', 'fnmatch', 'fractions', 'functools',
    'gc', 'getpass', 'gettext', 'glob', 'graphlib', 'gzip', 'hashlib', 'heapq', 'hmac',
    'html', 'http', 'imaplib', 'importlib', 'inspect', 'io', 'ipaddress', 'itertools',
    'json', 'keyword', 'linecache', 'locale', 'logging', 'lzma', 'mailbox', 'math',
    'mimetypes', 'mmap', 'multiprocessing', 'netrc', 'numbers', 'operator', 'os',
    'pathlib', 'pdb', 'pickle', 'pkgutil', 'platform', 'plistlib', 'poplib', 'posix',
    'pprint', 'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr', 'pydoc',
    'queue', 'quopri', 'random', 're', 'readline', 'reprlib', 'resource', 'rlcompleter',
    'runpy', 'sched', 'secrets', 'select', 'selectors', 'shelve', 'shlex', 'shutil',
    'signal', 'site', 'smtplib', 'socket', 'socketserver', 'sqlite3', 'ssl', 'stat',
    'statistics', 'string', 'stringprep', 'struct', 'subprocess', 'symtable', 'sys',
    'sysconfig', 'syslog', 'tabnanny', 'tarfile', 'tempfile', 'termios', 'test',
    'textwrap', 'threading', 'time', 'timeit', 'tkinter', 'token', 'tokenize',
    'tomllib', 'trace', 'traceback', 'tracemalloc', 'tty', 'turtle', 'types',
    'typing', 'unicodedata', 'unittest', 'urllib', 'uuid', 'venv', 'warnings',
    'wave', 'weakref', 'webbrowser', 'winreg', 'winsound', 'wsgiref', 'xdrlib',
    'xml', 'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib', 'zoneinfo',
}

NODE_BUILTINS = {
    'assert', 'async_hooks', 'buffer', 'child_process', 'cluster', 'console',
    'constants', 'crypto', 'dgram', 'diagnostics_channel', 'dns', 'domain', 'events',
    'fs', 'http', 'http2', 'https', 'inspector', 'module', 'net', 'os', 'path',
    'perf_hooks', 'process', 'punycode', 'querystring', 'readline', 'repl', 'stream',
    'string_decoder', 'sys', 'timers', 'tls', 'trace_events', 'tty', 'url', 'util',
    'v8', 'vm', 'wasi', 'worker_threads', 'zlib',
}

RUST_STD_CRATES = {'std', 'core', 'alloc', 'proc_macro', 'test', 'crate', 'self', 'super'}

BUNDLED_ADVISORIES = [
    {
        'id': 'GHSA-35jh-r3h4-6jhm',
        'ecosystem': 'npm',
        'name': 'lodash',
        'specifier': '<4.17.21',
        'severity': 'high',
        'summary': 'Command injection and prototype pollution in lodash before 4.17.21.',
    },
    {
        'id': 'GHSA-wf5p-g6vw-rhxx',
        'ecosystem': 'npm',
        'name': 'axios',
        'specifier': '<1.6.0',
        'severity': 'medium',
        'summary': 'Cross-Site Request Forgery token leakage in axios before 1.6.0.',
    },
    {
        'id': 'GHSA-952p-6rrq-rcjv',
        'ecosystem': 'npm',
        'name': 'micromatch',
        'specifier': '<4.0.8',
        'severity': 'medium',
        'summary': 'Regular expression denial of service (ReDoS) in micromatch before 4.0.8.',
    },
    {
        'id': 'GHSA-grv7-fg5c-xmjg',
        'ecosystem': 'npm',
        'name': 'braces',
        'specifier': '<3.0.3',
        'severity': 'medium',
        'summary': 'Uncontrolled resource consumption in braces before 3.0.3.',
    },
    {
        'id': 'GHSA-29mw-wpgm-hmr9',
        'ecosystem': 'npm',
        'name': 'semver',
        'specifier': '<7.5.2',
        'severity': 'medium',
        'summary': 'Regular expression denial of service in semver before 7.5.2.',
    },
    {
        'id': 'PYSEC-2023-74',
        'ecosystem': 'PyPI',
        'name': 'requests',
        'specifier': '<2.31.0',
        'severity': 'medium',
        'summary': 'Unintended leak of Proxy-Authorization header in requests before 2.31.0.',
    },
    {
        'id': 'PYSEC-2023-192',
        'ecosystem': 'PyPI',
        'name': 'urllib3',
        'specifier': '<2.0.7',
        'severity': 'medium',
        'summary': 'Cookie and authorization leakage on cross-origin redirect in urllib3.',
    },
    {
        'id': 'GHSA-jfmj-5v4g-7637',
        'ecosystem': 'PyPI',
        'name': 'cryptography',
        'specifier': '<42.0.4',
        'severity': 'high',
        'summary': 'NULL pointer dereference in PKCS12 parsing in cryptography before 42.0.4.',
    },
    {
        'id': 'PYSEC-2024-4',
        'ecosystem': 'PyPI',
        'name': 'jinja2',
        'specifier': '<3.1.3',
        'severity': 'medium',
        'summary': 'HTML attribute injection via xmlattr filter in Jinja2 before 3.1.3.',
    },
    {
        'id': 'PYSEC-2021-142',
        'ecosystem': 'PyPI',
        'name': 'pyyaml',
        'specifier': '<5.4',
        'severity': 'critical',
        'summary': 'Arbitrary code execution via full_load in PyYAML before 5.4.',
    },
    {
        'id': 'RUSTSEC-2023-0044',
        'ecosystem': 'crates.io',
        'name': 'openssl',
        'specifier': '<0.10.55',
        'severity': 'medium',
        'summary': 'X.509 policy verification denial of service in openssl crate.',
    },
    {
        'id': 'RUSTSEC-2021-0124',
        'ecosystem': 'crates.io',
        'name': 'tokio',
        'specifier': '<1.13.1',
        'severity': 'medium',
        'summary': 'Data race in oneshot channel after close in tokio before 1.13.1.',
    },
]


def _strip_jsonc(text: str) -> str:
    # Strip // and /* */ comments outside strings and trailing commas for tsconfig/jsconfig
    pattern = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\r\n]*|/\*[\s\S]*?\*/')
    stripped = pattern.sub(lambda m: m.group(0) if m.group(0).startswith(('"', "'")) else '', text)
    return re.sub(r',\s*([}\]])', r'\1', stripped)


def _normalize_pkg_name(ecosystem: str, name: str) -> str:
    if ecosystem == 'PyPI':
        return re.sub(r'[-_.]+', '-', (name or '').strip().lower())
    return (name or '').strip()


def _semver_to_pep440(spec: str) -> str | None:
    if not spec or not isinstance(spec, str):
        return None
    raw = spec.strip()
    if not raw or raw in {'*', 'latest', 'workspace', 'path/git'} or raw.startswith(('workspace:', 'file:', 'link:', 'git+', 'http:', 'https:', 'npm:')):
        return None
    # Extract requirement part if full PEP 508 string like "pkg>=1.0,<2.0"
    m_pep = re.match(r'^[A-Za-z0-9_.-]+(?:\[[^\]]*\])?\s*([<>=!~].*)$', raw)
    if m_pep:
        raw = m_pep.group(1).strip().split(';', 1)[0].strip()
    if '||' in raw:
        # Handle union ranges separately in version_satisfies
        return None
    parts = [p.strip() for p in re.split(r',|\s+(?=[<>=!~^])', raw) if p.strip()]
    converted = []
    for part in parts:
        part = part.removeprefix('v')
        if part.startswith('^'):
            ver_s = part[1:].strip().removeprefix('v')
            m = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?', ver_s)
            if not m:
                return None
            major = int(m.group(1))
            minor = int(m.group(2) or 0)
            patch = int(m.group(3) or 0)
            if major > 0:
                upper = f'{major + 1}.0.0'
            elif minor > 0:
                upper = f'0.{minor + 1}.0'
            else:
                upper = f'0.0.{patch + 1}'
            converted.append(f'>={major}.{minor}.{patch},<{upper}')
        elif part.startswith('~') and not part.startswith('~='):
            ver_s = part[1:].strip().removeprefix('v')
            m = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?', ver_s)
            if not m:
                return None
            major = int(m.group(1))
            minor = int(m.group(2) or 0)
            patch = int(m.group(3) or 0)
            converted.append(f'>={major}.{minor}.{patch},<{major}.{minor + 1}.0')
        elif re.match(r'^\d+\.\d+(?:\.\d+)?(?:[-+A-Za-z0-9.]+)?$', part):
            converted.append(f'=={part}')
        elif re.match(r'^(?:>=|<=|==|!=|~=|>|<)\s*\d+', part):
            converted.append(re.sub(r'\s+', '', part))
        else:
            return None
    return ','.join(converted) if converted else None


def version_satisfies(version_str: str | None, requirement: str | None) -> bool | None:
    """Return True/False if version satisfaction can be determined, or None if indeterminate."""
    if not version_str or not requirement:
        return None
    clean_ver = str(version_str).strip().removeprefix('v')
    try:
        ver = Version(clean_ver.split('+', 1)[0])
    except InvalidVersion:
        return None
    req = str(requirement).strip()
    if '||' in req:
        outcomes = [version_satisfies(clean_ver, branch.strip()) for branch in req.split('||') if branch.strip()]
        valid = [o for o in outcomes if o is not None]
        return any(valid) if valid else None
    pep_spec = _semver_to_pep440(req)
    if not pep_spec:
        return None
    try:
        spec_set = SpecifierSet(pep_spec)
        return spec_set.contains(ver, prereleases=True)
    except InvalidSpecifier:
        return None


def classify_license(license_str: str | None) -> str:
    if not license_str or not isinstance(license_str, str):
        return 'unknown'
    norm = license_str.strip().upper()
    if not norm or norm in {'UNKNOWN', 'NONE', 'UNLICENSED', 'SEE LICENSE IN LICENSE'}:
        return 'unknown'
    if norm in PERMISSIVE_LICENSES or any(tok in PERMISSIVE_LICENSES for tok in re.split(r'\s+OR\s+|\s*/\s*', norm)):
        return 'permissive'
    if norm in STRONG_COPYLEFT_LICENSES or any(k in norm for k in ('AGPL', 'GPL-2', 'GPL-3', 'SSPL')) and 'LGPL' not in norm:
        return 'strong_copyleft'
    if norm in WEAK_COPYLEFT_LICENSES or any(k in norm for k in ('LGPL', 'MPL-2', 'EPL-', 'CDDL')):
        return 'weak_copyleft'
    return 'custom_or_proprietary'


def match_advisories(packages: list[dict], advisories: list[dict]) -> list[dict]:
    matches = []
    seen = set()
    for pkg in packages:
        eco = pkg.get('ecosystem', '')
        name = _normalize_pkg_name(eco, pkg.get('name', ''))
        ver = pkg.get('version')
        if not name or not ver:
            continue
        for adv in advisories:
            adv_eco = adv.get('ecosystem', '')
            adv_name = _normalize_pkg_name(adv_eco, adv.get('name', ''))
            if adv_eco != eco or adv_name != name:
                continue
            matched = False
            adv_ver = adv.get('version')
            adv_spec = adv.get('specifier') or adv.get('affected_range') or adv.get('range')
            adv_versions = adv.get('versions') or []
            if adv_ver and str(adv_ver).lstrip('=v') == str(ver).lstrip('v'):
                matched = True
            elif adv_ver and any(op in str(adv_ver) for op in ('<', '>', '=', '~', '^')) and version_satisfies(ver, str(adv_ver)) is True:
                matched = True
            elif adv_spec and version_satisfies(ver, str(adv_spec)) is True:
                matched = True
            elif ver in adv_versions:
                matched = True
            if matched:
                key = (pkg['id'], adv.get('id'))
                if key not in seen:
                    seen.add(key)
                    matches.append({
                        'package_id': pkg['id'],
                        'ecosystem': eco,
                        'name': pkg.get('name'),
                        'version': ver,
                        'advisory_id': adv.get('id'),
                        'severity': adv.get('severity'),
                        'summary': adv.get('summary'),
                        'matched_constraint': adv_spec or adv_ver,
                    })
    return matches


def inventory(sources: dict[str, str], parsed_files: dict[str, dict] | None = None) -> dict:
    declarations, packages, edges, errors, licenses = [], [], [], [], []
    configs, aliases, peer_constraints = [], [], []
    workspace_packages = set()

    def declared(path, ecosystem, name, requirement, section):
        declarations.append({
            'path': path,
            'ecosystem': ecosystem,
            'name': name,
            'requirement': str(requirement),
            'section': section,
        })

    for path, text in sorted(sources.items()):
        filename = PurePosixPath(path).name
        parent_dir = str(PurePosixPath(path).parent)
        if parent_dir == '.':
            parent_dir = ''
        if filename in {'tsconfig.json', 'jsconfig.json'} or (filename.startswith('tsconfig.') and filename.endswith('.json')):
            try:
                doc = json.loads(_strip_jsonc(text))
                compiler = doc.get('compilerOptions') or {}
                base_url = compiler.get('baseUrl', '.')
                base_prefix = str(PurePosixPath(parent_dir) / base_url) if parent_dir else str(PurePosixPath(base_url))
                if base_prefix == '.':
                    base_prefix = ''
                path_map = compiler.get('paths') or {}
                for alias_pat, targets in path_map.items():
                    if not isinstance(targets, list):
                        continue
                    prefix = alias_pat[:-1] if alias_pat.endswith('*') else alias_pat
                    resolved_targets = []
                    for target in targets:
                        if not isinstance(target, str):
                            continue
                        t_clean = target[:-1] if target.endswith('*') else target
                        combined = str(PurePosixPath(base_prefix) / t_clean) if base_prefix else str(PurePosixPath(t_clean))
                        resolved_targets.append(combined.lstrip('./'))
                    aliases.append({
                        'path': path,
                        'pattern': alias_pat,
                        'prefix': prefix,
                        'targets': resolved_targets,
                    })
                configs.append({
                    'path': path,
                    'kind': 'typescript_config',
                    'target': compiler.get('target'),
                    'module': compiler.get('module'),
                    'moduleResolution': compiler.get('moduleResolution'),
                    'strict': compiler.get('strict'),
                    'baseUrl': compiler.get('baseUrl'),
                    'aliases_count': len(path_map),
                })
            except Exception as exc:
                errors.append({'path': path, 'reason': f'Invalid compiler config: {type(exc).__name__}'})
            continue

        if filename not in {
            'package.json', 'package-lock.json', 'Cargo.toml', 'Cargo.lock',
            'pyproject.toml', 'uv.lock', 'poetry.lock', 'go.mod', 'go.sum', 'requirements.txt',
        }:
            continue
        try:
            if filename == 'package.json':
                doc = json.loads(text)
                if doc.get('name'):
                    workspace_packages.add(doc['name'])
                for section in ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'):
                    for name, requirement in (doc.get(section) or {}).items():
                        declared(path, 'npm', name, requirement, section)
                        if section == 'peerDependencies':
                            peer_constraints.append({'path': path, 'ecosystem': 'npm', 'name': name, 'requirement': str(requirement)})
                if doc.get('license'):
                    licenses.append({
                        'path': path,
                        'name': doc.get('name'),
                        'license': doc['license'],
                        'category': classify_license(doc['license']),
                        'evidence': 'manifest',
                    })
                if doc.get('workspaces') or doc.get('main') or doc.get('exports') or doc.get('scripts'):
                    configs.append({
                        'path': path,
                        'kind': 'npm_manifest',
                        'name': doc.get('name'),
                        'workspaces': doc.get('workspaces'),
                        'main': doc.get('main'),
                        'module': doc.get('module'),
                        'scripts': sorted((doc.get('scripts') or {}).keys()),
                    })
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
                    lic = pkg.get('license')
                    packages.append({
                        'id': identity,
                        'ecosystem': 'npm',
                        'name': name,
                        'version': pkg.get('version'),
                        'path': path,
                        'location': location,
                        'license': lic,
                        'license_category': classify_license(lic) if isinstance(lic, str) else 'unknown',
                        'source': _safe_url(pkg.get('resolved')),
                        'integrity_present': bool(pkg.get('integrity')),
                    })
                    if lic and isinstance(lic, str):
                        licenses.append({
                            'path': path,
                            'name': name,
                            'version': pkg.get('version'),
                            'license': lic,
                            'category': classify_license(lic),
                            'evidence': 'lockfile',
                        })
                    for peer_name, peer_req in (pkg.get('peerDependencies') or {}).items():
                        peer_constraints.append({
                            'path': path,
                            'source_package': f"{name}@{pkg.get('version')}",
                            'ecosystem': 'npm',
                            'name': peer_name,
                            'requirement': str(peer_req),
                        })
                for location, pkg in locked.items():
                    for name in (pkg.get('dependencies') or {}):
                        target = _npm_resolve(location, name, ids)
                        edges.append({
                            'source': ids.get(location, f'{path}:root'),
                            'target': target,
                            'name': name,
                            'resolution': 'lockfile' if target else 'unresolved',
                        })
                if not locked and doc.get('dependencies'):
                    errors.append({'path': path, 'reason': 'npm v1 lockfile is not supported; upgrade or provide a v2/v3 lockfile'})
            elif filename in {'Cargo.toml', 'pyproject.toml'}:
                doc = tomllib.loads(text)
                if filename == 'Cargo.toml':
                    sections = [(s, doc.get(s, {})) for s in ('dependencies', 'dev-dependencies', 'build-dependencies')]
                    sections += [
                        (f'target.{target}.{s}', table.get(s, {}))
                        for target, table in doc.get('target', {}).items()
                        for s in ('dependencies', 'dev-dependencies', 'build-dependencies')
                    ]
                    for section, items in sections:
                        for name, value in items.items():
                            actual = value.get('package', name) if isinstance(value, dict) else name
                            requirement = value.get('version', 'workspace' if value.get('workspace') else 'path/git') if isinstance(value, dict) else value
                            declared(path, 'crates.io', actual, requirement, section)
                    pkg = doc.get('package', {})
                    if pkg.get('name'):
                        workspace_packages.add(pkg['name'])
                        workspace_packages.add(pkg['name'].replace('-', '_'))
                    if pkg.get('license'):
                        licenses.append({
                            'path': path,
                            'name': pkg.get('name'),
                            'license': pkg['license'],
                            'category': classify_license(pkg['license']),
                            'evidence': 'manifest',
                        })
                    if doc.get('workspace') or pkg:
                        configs.append({
                            'path': path,
                            'kind': 'cargo_manifest',
                            'name': pkg.get('name'),
                            'edition': pkg.get('edition'),
                            'workspace_members': (doc.get('workspace') or {}).get('members', []),
                        })
                else:
                    proj = doc.get('project', {})
                    if proj.get('name'):
                        workspace_packages.add(proj['name'])
                        workspace_packages.add(proj['name'].replace('-', '_'))
                    lic = proj.get('license')
                    lic_text = lic.get('text') or lic.get('file') if isinstance(lic, dict) else lic
                    if lic_text and isinstance(lic_text, str):
                        licenses.append({
                            'path': path,
                            'name': proj.get('name'),
                            'license': lic_text,
                            'category': classify_license(lic_text),
                            'evidence': 'manifest',
                        })
                    for requirement in proj.get('dependencies', []):
                        name = re.match(r'[\w.-]+', requirement)
                        if name:
                            declared(path, 'PyPI', name[0], requirement, 'dependencies')
                    for section, items in proj.get('optional-dependencies', {}).items():
                        for requirement in items:
                            name = re.match(r'[\w.-]+', requirement)
                            if name:
                                declared(path, 'PyPI', name[0], requirement, f'optional.{section}')
                    for group_name, items in (doc.get('dependency-groups') or {}).items():
                        for requirement in items:
                            if isinstance(requirement, str):
                                name = re.match(r'[\w.-]+', requirement)
                                if name:
                                    declared(path, 'PyPI', name[0], requirement, f'group.{group_name}')
                    configs.append({
                        'path': path,
                        'kind': 'python_manifest',
                        'name': proj.get('name'),
                        'requires_python': proj.get('requires-python'),
                        'scripts': sorted((proj.get('scripts') or {}).keys()),
                    })
            elif filename in {'Cargo.lock', 'uv.lock', 'poetry.lock'}:
                doc = tomllib.loads(text)
                ecosystem = 'crates.io' if filename == 'Cargo.lock' else 'PyPI'
                rows = doc.get('package', [])
                lookup = defaultdict(list)
                for pkg in rows:
                    identity = _locked_id(path, pkg)
                    source = pkg.get('source')
                    packages.append({
                        'id': identity,
                        'ecosystem': ecosystem,
                        'name': pkg['name'],
                        'version': pkg.get('version'),
                        'path': path,
                        'source': _safe_url(source) if isinstance(source, str) else _safe_source(source),
                        'license': None,
                        'license_category': 'unknown',
                        'integrity_present': bool(pkg.get('checksum') or pkg.get('sdist', {}).get('hash') or pkg.get('wheels')),
                    })
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
                        edges.append({
                            'source': source,
                            'target': candidates[0] if len(candidates) == 1 else None,
                            'name': name,
                            'resolution': 'lockfile' if len(candidates) == 1 else 'unresolved',
                        })
            elif filename == 'go.mod':
                in_require = False
                for line in text.splitlines():
                    line = line.split('//', 1)[0].strip()
                    if line.startswith('module '):
                        mod_name = line.removeprefix('module ').strip()
                        workspace_packages.add(mod_name)
                        configs.append({'path': path, 'kind': 'go_module', 'module': mod_name})
                    elif line == 'require (':
                        in_require = True
                    elif line == ')':
                        in_require = False
                    elif line.startswith('require ') or in_require:
                        parts = line.removeprefix('require ').split()
                        if len(parts) >= 2:
                            declared(path, 'Go', parts[0], parts[1], 'require')
            elif filename == 'go.sum':
                seen_go = set()
                for line in text.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        mod_name = parts[0]
                        ver = parts[1].removesuffix('/go.mod').removeprefix('v')
                        key = (mod_name, ver)
                        if key not in seen_go:
                            seen_go.add(key)
                            identity = f'{path}:{mod_name}@{ver}'
                            packages.append({
                                'id': identity,
                                'ecosystem': 'Go',
                                'name': mod_name,
                                'version': ver,
                                'path': path,
                                'source': mod_name,
                                'license': None,
                                'license_category': 'unknown',
                                'integrity_present': bool(parts[2]),
                            })
            elif filename == 'requirements.txt':
                for line in text.splitlines():
                    name = re.match(r'([\w.-]+)(?:\[[^]]+\])?\s*([<>=!~].*)?$', line.strip())
                    if name and not line.lstrip().startswith('#'):
                        declared(path, 'PyPI', name[1], name[0], 'requirements')
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            errors.append({'path': path, 'reason': f'Invalid manifest: {type(exc).__name__}'})

    versions = defaultdict(set)
    pkg_by_eco_name = defaultdict(list)
    for pkg in packages:
        eco_key = (pkg['ecosystem'], _normalize_pkg_name(pkg['ecosystem'], pkg['name']))
        pkg_by_eco_name[eco_key].append(pkg)
        if pkg['version']:
            versions[(pkg['ecosystem'], pkg['name'])].add(pkg['version'])

    multiple = []
    for (e, n), v in sorted(versions.items()):
        if len(v) > 1:
            sorted_v = sorted(v)
            majors = {ver.split('.', 1)[0] for ver in sorted_v if ver}
            multiple.append({
                'ecosystem': e,
                'name': n,
                'versions': sorted_v,
                'major_divergence': len(majors) > 1,
                'interpretation': 'multiple versions; major version divergence detected' if len(majors) > 1 else 'multiple versions; not proof of incompatibility',
            })

    compatibility_issues = []
    for decl in declarations:
        eco = decl['ecosystem']
        norm_name = _normalize_pkg_name(eco, decl['name'])
        locked_list = pkg_by_eco_name.get((eco, norm_name), [])
        if not locked_list:
            continue
        satisfied = [version_satisfies(p.get('version'), decl.get('requirement')) for p in locked_list if p.get('version')]
        checked = [s for s in satisfied if s is not None]
        if checked and not any(checked):
            compatibility_issues.append({
                'kind': 'manifest_lock_mismatch',
                'path': decl['path'],
                'ecosystem': eco,
                'name': decl['name'],
                'declared_requirement': decl['requirement'],
                'locked_versions': sorted({p.get('version') for p in locked_list if p.get('version')}),
            })

    peer_conflicts = []
    for peer in peer_constraints:
        eco = peer['ecosystem']
        norm_name = _normalize_pkg_name(eco, peer['name'])
        locked_list = pkg_by_eco_name.get((eco, norm_name), [])
        if not locked_list:
            continue
        satisfied = [version_satisfies(p.get('version'), peer.get('requirement')) for p in locked_list if p.get('version')]
        checked = [s for s in satisfied if s is not None]
        if checked and not any(checked):
            peer_conflicts.append({
                'path': peer['path'],
                'source_package': peer.get('source_package', 'manifest'),
                'ecosystem': eco,
                'name': peer['name'],
                'peer_requirement': peer['requirement'],
                'locked_versions': sorted({p.get('version') for p in locked_list if p.get('version')}),
            })

    license_counts = defaultdict(int)
    project_licenses = [lic for lic in licenses if lic.get('evidence') == 'manifest']
    project_is_permissive = any(lic.get('category') == 'permissive' for lic in project_licenses)
    license_conflicts = []
    for lic in licenses:
        cat = lic.get('category') or classify_license(lic.get('license'))
        lic['category'] = cat
        license_counts[cat] += 1
        if project_is_permissive and cat == 'strong_copyleft' and lic.get('evidence') == 'lockfile':
            license_conflicts.append({
                'package': lic.get('name'),
                'version': lic.get('version'),
                'license': lic.get('license'),
                'reason': 'Strong copyleft package locked in a permissive manifest project.',
            })

    bundled_matches = match_advisories(packages, BUNDLED_ADVISORIES)
    usage = analyze_usage(declarations, parsed_files or {}, workspace_packages, sources)
    sbom_doc = generate_sbom(packages, edges, licenses)

    return {
        'declarations': declarations,
        'packages': packages,
        'edges': edges,
        'multiple_versions': multiple,
        'compatibility_issues': compatibility_issues,
        'peer_conflicts': peer_conflicts,
        'configs': configs,
        'aliases': aliases,
        'unused_dependencies': usage['unused_dependencies'],
        'undeclared_imports': usage['undeclared_imports'],
        'licenses': licenses,
        'license_summary': {
            'counts': dict(license_counts),
            'conflicts': license_conflicts,
        },
        'bundled_advisories': {
            'status': 'completed' if packages else 'no_locked_packages',
            'advisory_count': len(BUNDLED_ADVISORIES),
            'matches': bundled_matches,
        },
        'sbom': sbom_doc,
        'errors': errors,
        'methodology': 'manifest-lockfile-v2-semver-sbom',
        'limitations': [
            'Only recorded manifests and supported lockfiles are examined.',
            'Missing license metadata is unknown, not an unrestricted license.',
            'Version ranges are evaluated via PEP-440 and SemVer conversion rules.',
        ],
    }


def analyze_usage(
    declarations: list[dict],
    parsed_files: dict[str, dict],
    workspace_packages: set[str],
    sources: dict[str, str] | None = None,
) -> dict:
    """Compare source imports against declared manifest packages to find unused and undeclared dependencies."""
    if not parsed_files:
        return {'unused_dependencies': [], 'undeclared_imports': []}

    local_top_modules = set()
    for path in parsed_files:
        parts = PurePosixPath(path).parts
        if parts:
            local_top_modules.add(PurePosixPath(parts[0]).stem)
        stem = PurePosixPath(path).stem
        if stem != '__init__':
            local_top_modules.add(stem)
        if len(parts) >= 2 and parts[0] in {'src', 'backend', 'lib', 'app', 'packages'}:
            local_top_modules.add(PurePosixPath(parts[1]).stem)

    imported_by_eco: dict[str, set[str]] = defaultdict(set)
    import_locations: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for path, item in sorted(parsed_files.items()):
        lang = item.get('language')
        for imp in item.get('imports', []):
            mod = (imp.get('source') or imp.get('module') or '').strip()
            if not mod or mod.startswith(('.', '/', '@/', '~/', 'http://', 'https://', 'data:')):
                continue
            if lang in {'typescript', 'tsx', 'javascript', 'jsx', 'html', 'css'}:
                if mod.startswith('node:'):
                    continue
                if mod.startswith('@'):
                    parts = mod.split('/')
                    pkg_name = '/'.join(parts[:2]) if len(parts) >= 2 else parts[0]
                else:
                    pkg_name = mod.split('/', 1)[0]
                if pkg_name in NODE_BUILTINS or pkg_name in local_top_modules or pkg_name in workspace_packages:
                    continue
                imported_by_eco['npm'].add(pkg_name)
                import_locations[('npm', pkg_name)].append({'path': path, 'line': imp.get('line', 1), 'module': mod})
            elif lang == 'python':
                top = mod.split('.', 1)[0]
                if top in PYTHON_STDLIB or top in local_top_modules or top in workspace_packages:
                    continue
                imported_by_eco['PyPI'].add(top.lower())
                import_locations[('PyPI', top.lower())].append({'path': path, 'line': imp.get('line', 1), 'module': mod})
            elif lang == 'rust':
                top = mod.split('::', 1)[0]
                if top in RUST_STD_CRATES or top in local_top_modules or top in workspace_packages:
                    continue
                imported_by_eco['crates.io'].add(top)
                import_locations[('crates.io', top)].append({'path': path, 'line': imp.get('line', 1), 'module': mod})
            elif lang == 'go':
                if '/' not in mod:
                    continue
                imported_by_eco['Go'].add(mod)
                import_locations[('Go', mod)].append({'path': path, 'line': imp.get('line', 1), 'module': mod})

    # Also check build/plugin config files (excluding manifest dependency lists themselves)
    all_config_text = '\n'.join(text for p, text in (sources or {}).items() if PurePosixPath(p).name in {
        'vite.config.ts', 'vite.config.js', 'tsconfig.json', 'eslint.config.js', 'postcss.config.js', 'tailwind.config.js',
    })

    declared_by_eco: dict[str, set[str]] = defaultdict(set)
    unused_dependencies = []
    seen_unused = set()

    for decl in declarations:
        eco = decl['ecosystem']
        name = decl['name']
        section = decl.get('section', '')
        norm = _normalize_pkg_name(eco, name)
        declared_by_eco[eco].add(norm)
        if eco == 'npm':
            declared_by_eco[eco].add(name)
            if name.startswith('@types/') or any(s in section for s in ('devDependencies', 'build', 'optional', 'group.')):
                continue
            used = (
                name in imported_by_eco['npm']
                or name in all_config_text
                or any(imp.startswith(f'{name}/') for imp in imported_by_eco['npm'])
            )
            if not used and (decl['path'], name) not in seen_unused:
                seen_unused.add((decl['path'], name))
                unused_dependencies.append({
                    'path': decl['path'],
                    'ecosystem': eco,
                    'name': name,
                    'section': section,
                    'reason': 'Declared runtime dependency has no matching source import or config reference.',
                })
        elif eco == 'PyPI':
            if any(s in section for s in ('optional', 'group.', 'dev')):
                continue
            candidate_imports = {norm.replace('-', '_'), norm} | PYPI_IMPORT_ALIASES.get(norm, set())
            if norm.startswith('tree-sitter-'):
                candidate_imports.add(norm.replace('-', '_'))
                candidate_imports.add('tree_sitter_language_pack')
            used = bool(candidate_imports & imported_by_eco['PyPI']) or (name in all_config_text)
            if not used and (decl['path'], name) not in seen_unused:
                seen_unused.add((decl['path'], name))
                unused_dependencies.append({
                    'path': decl['path'],
                    'ecosystem': eco,
                    'name': name,
                    'section': section,
                    'reason': 'Declared Python dependency has no matching import in indexed Python files.',
                })
        elif eco == 'crates.io':
            if 'dev' in section or 'build' in section:
                continue
            crate_ident = name.replace('-', '_')
            used = crate_ident in imported_by_eco['crates.io'] or name in imported_by_eco['crates.io'] or name in all_config_text
            if not used and (decl['path'], name) not in seen_unused:
                seen_unused.add((decl['path'], name))
                unused_dependencies.append({
                    'path': decl['path'],
                    'ecosystem': eco,
                    'name': name,
                    'section': section,
                    'reason': 'Declared Rust crate has no explicit use statement in indexed Rust files.',
                })

    undeclared_imports = []
    # Only flag undeclared imports for an ecosystem if at least one manifest for that ecosystem exists
    for eco, imports in sorted(imported_by_eco.items()):
        if not declared_by_eco.get(eco):
            continue
        declared_norm = declared_by_eco[eco]
        expanded_declared = set(declared_norm)
        if eco == 'PyPI':
            for d in list(declared_norm):
                expanded_declared.add(d.replace('-', '_'))
                expanded_declared |= PYPI_IMPORT_ALIASES.get(d, set())
        elif eco == 'crates.io':
            for d in list(declared_norm):
                expanded_declared.add(d.replace('-', '_'))
        for imp_pkg in sorted(imports):
            if imp_pkg not in expanded_declared and _normalize_pkg_name(eco, imp_pkg) not in expanded_declared:
                if eco == 'Go' and any(imp_pkg.startswith(d) for d in expanded_declared):
                    continue
                locs = import_locations.get((eco, imp_pkg), [])
                undeclared_imports.append({
                    'ecosystem': eco,
                    'package': imp_pkg,
                    'locations': locs[:5],
                    'reason': f'Imported in source code but not declared in {eco} manifest.',
                })

    return {
        'unused_dependencies': unused_dependencies,
        'undeclared_imports': undeclared_imports,
    }


def generate_sbom(packages: list[dict], edges: list[dict], licenses: list[dict]) -> dict:
    """Generate a CycloneDX 1.5 compatible Software Bill of Materials (SBOM) summary."""
    purl_prefix = {
        'npm': 'pkg:npm/',
        'PyPI': 'pkg:pypi/',
        'crates.io': 'pkg:cargo/',
        'Go': 'pkg:golang/',
    }
    components = []
    for pkg in packages:
        eco = pkg.get('ecosystem', 'generic')
        name = pkg.get('name', 'unknown')
        ver = pkg.get('version') or '0.0.0'
        prefix = purl_prefix.get(eco, f'pkg:{eco.lower()}/')
        purl = f'{prefix}{name}@{ver}'
        comp = {
            'type': 'library',
            'bom-ref': pkg['id'],
            'name': name,
            'version': ver,
            'purl': purl,
            'ecosystem': eco,
            'integrity_verified': bool(pkg.get('integrity_present')),
        }
        if pkg.get('license'):
            comp['licenses'] = [{'license': {'id': str(pkg['license'])}}]
        components.append(comp)

    dep_map: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.get('source') and edge.get('target'):
            dep_map[edge['source']].append(edge['target'])
    dependencies_block = [{'ref': ref, 'dependsOn': sorted(set(targets))} for ref, targets in sorted(dep_map.items())]

    return {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.5',
        'version': 1,
        'component_count': len(components),
        'components': components[:250],
        'dependencies': dependencies_block[:250],
    }


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
