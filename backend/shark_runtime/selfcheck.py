"""Release smoke check: bundled parsers, intelligence engines, local index and browser executable. No project execution."""
import argparse
import importlib
import json
import sqlite3
from pathlib import Path

from .codebase.syntax import LANGUAGES, parse

FIXTURES = {
    'python': 'def sample():\n    return 1\n',
    'typescript': 'function sample() { return 1; }',
    'tsx': 'function Sample() { return <div/>; }',
    'javascript': 'function sample() { return 1; }',
    'rust': 'fn sample() {}',
    'go': 'package main\nfunc sample() {}',
    'java': 'class Sample {}',
    'c': 'int sample() { return 1; }',
    'cpp': 'class Sample {};',
    'csharp': 'class Sample {}',
    'ruby': 'class Sample\nend\n',
    'kotlin': 'class Sample {}\n',
    'php': '<?php function sample() { return 1; }\n',
    'scala': 'object Sample {}\n',
    'lua': 'function sample()\n  return 1\nend\n',
    'bash': 'sample() {\n  echo 1\n}\n',
    'zig': 'pub fn sample() void {}\n',
}

BUNDLED_LIBRARIES = (
    'ast_grep_py',
    'sqlglot',
    'radon',
    'vulture',
    'dulwich',
    'rapidfuzz',
    'numpy',
    'networkx',
    'packaging',
    'docstring_parser',
)


def check(require_browser=False):
    checks = []
    done = set()
    for extension, (language, _, _) in LANGUAGES.items():
        if language in done:
            continue
        done.add(language)
        result = parse('sample' + extension, FIXTURES[language])
        checks.append({'component': language, 'ready': result['parser'] == 'tree-sitter' and bool(result['symbols'])})
    for lib_name in BUNDLED_LIBRARIES:
        try:
            importlib.import_module(lib_name)
            checks.append({'component': lib_name, 'ready': True})
        except ImportError:
            checks.append({'component': lib_name, 'ready': False})
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute('CREATE VIRTUAL TABLE search USING fts5(body)')
        checks.append({'component': 'sqlite-fts5', 'ready': True})
    finally:
        connection.close()
    from .mcp_server import server
    checks.append({'component': 'mcp', 'ready': server is not None})
    if require_browser:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            checks.append({'component': 'chromium', 'ready': Path(playwright.chromium.executable_path).is_file()})
    return {'schema': 'shark-core-selfcheck-v1', 'ready': all(c['ready'] for c in checks), 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-browser', action='store_true')
    args = parser.parse_args()
    result = check(args.require_browser)
    print(json.dumps(result))
    raise SystemExit(0 if result['ready'] else 1)


if __name__ == '__main__':
    main()
