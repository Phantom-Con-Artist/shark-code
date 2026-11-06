"""Explainable syntax checks. Findings are review candidates, not exploit confirmations."""
from __future__ import annotations

import ast
import hashlib
import re
from collections import defaultdict
from pathlib import PurePosixPath

THRESHOLDS = {'function_lines': 80, 'class_lines': 400, 'cyclomatic_syntax': 15, 'cognitive_nesting': 20, 'max_nesting': 5}
# Patterns intentionally return no source snippets or matched credential values.
SECRETS = [
    ('private-key', r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    ('aws-access-key', r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    ('github-token', r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    ('credential-literal', r'''(?i)\b(?:api[_-]?key|secret[_-]?key|password|access[_-]?token)\s*[:=]\s*["']([^"'\n]{12,})["']'''),
]
REVIEW_PATTERNS = [
    ('rust-unsafe', {'.rs'}, r'\bunsafe\s*(?:\{|fn\b|impl\b|trait\b)', 'Review the unsafe invariant and every caller that relies on it.'),
    ('rust-ffi', {'.rs'}, r'\bextern\s*"(?:C|system)(?:-unwind)?"', 'Review ABI, ownership, pointer lifetimes and unwind behavior at this FFI boundary.'),
    ('javascript-eval', {'.js', '.jsx', '.ts', '.tsx'}, r'\beval\s*\(', 'Review where the evaluated input originates.'),
    ('weak-crypto', {'.py', '.js', '.ts', '.go'}, r'\b(?:hashlib\.)?(?:md5|sha1)\s*\(', 'Review whether this hash is used for security; non-security checksums may be intentional.'),
    ('c-memory-copy', {'.c', '.cpp', '.h', '.hpp'}, r'\b(?:strcpy|strcat|sprintf|gets)\s*\(', 'Review buffer sizes and whether inputs can cross a trust boundary.'),
]


def security(path, text):
    findings = []
    def add(rule, line, message, evidence='syntax_pattern'):
        findings.append({'id': hashlib.sha256(f'{path}:{line}:{rule}'.encode()).hexdigest()[:24], 'rule': rule,
                         'path': path, 'line': line, 'status': 'needs_review', 'message': message,
                         'evidence_kind': evidence, 'secret_redacted': True})
    for rule, pattern in SECRETS:
        for match in re.finditer(pattern, text):
            if rule == 'credential-literal' and re.search(r'(?i)(example|placeholder|changeme|your[_-]|\$\{|\{\{|process\.env)', match[1]):
                continue
            add(rule, text.count('\n', 0, match.start()) + 1, 'Potential hardcoded credential. Value omitted; inspect the source and rotate if it is real.')
    extension = PurePosixPath(path).suffix
    for rule, languages, pattern, message in REVIEW_PATTERNS:
        if extension in languages:
            for match in re.finditer(pattern, text):
                add(rule, text.count('\n', 0, match.start()) + 1, message)
    if extension in {'.py', '.pyi'}:
        try:
            tree = ast.parse(text)
        except (SyntaxError, RecursionError):
            return findings
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                aliases.update((a.asname or a.name, a.name) for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                aliases.update((a.asname or a.name, f'{node.module}.{a.name}') for a in node.names)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            parts = name.split('.')
            name = '.'.join([aliases.get(parts[0], parts[0]), *parts[1:]])
            if name in {'eval', 'exec'}:
                add('dynamic-code', node.lineno, 'Dynamic code execution; review input origin and allowed operations.', 'python_ast')
            elif name in {'pickle.loads', 'pickle.load', 'dill.loads', 'marshal.loads', 'yaml.load'}:
                if name != 'yaml.load' or not any(k.arg == 'Loader' and _call_name(k.value).endswith('SafeLoader') for k in node.keywords):
                    add('deserialization', node.lineno, 'Deserialization may execute code; review whether input is trusted.', 'python_ast')
            elif name in {'os.system', 'os.popen'} or name.startswith('subprocess.') and any(k.arg == 'shell' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                add('shell-execution', node.lineno, 'Shell execution; trace command construction and input origin before classifying injection.', 'python_ast')
            elif name.endswith(('.execute', '.executemany')) and node.args and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
                add('constructed-sql', node.lineno, 'Dynamically constructed query; inspect parameterization and input provenance.', 'python_ast')
    return findings[:1000]


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f'{prefix}.{node.attr}' if prefix else node.attr
    return ''


def quality(records, sources):
    findings, metrics, clones = [], [], defaultdict(list)
    for record in records:
        metrics.extend(record['metrics'])
        for metric in record['metrics']:
            for name in ('cyclomatic_syntax', 'cognitive_nesting', 'max_nesting'):
                if metric[name] >= THRESHOLDS[name]:
                    findings.append({'rule': f'high-{name}', 'path': metric['path'], 'line': metric['line'],
                                     'value': metric[name], 'threshold': THRESHOLDS[name], 'symbol_id': metric['symbol_id']})
            if metric['lines'] > THRESHOLDS['function_lines']:
                findings.append({'rule': 'oversized-function', 'path': metric['path'], 'line': metric['line'],
                                 'value': metric['lines'], 'threshold': THRESHOLDS['function_lines']})
        for symbol in record['symbols']:
            if symbol['kind'] == 'class' and symbol['end_line'] - symbol['line'] + 1 > THRESHOLDS['class_lines']:
                findings.append({'rule': 'oversized-class', 'path': record['path'], 'line': symbol['line'],
                                 'value': symbol['end_line'] - symbol['line'] + 1, 'threshold': THRESHOLDS['class_lines']})
        for duplicate in record['duplicates']:
            clones[duplicate['fingerprint']].append({k: duplicate[k] for k in ('symbol_id', 'path', 'line')})
        if record['language'] == 'python':
            try:
                tree = ast.parse(sources[record['path']])
                for node in ast.walk(tree):
                    for field in ('body', 'orelse', 'finalbody'):
                        body = getattr(node, field, None)
                        if isinstance(body, list):
                            terminated = False
                            for statement in body:
                                if terminated and isinstance(statement, ast.stmt):
                                    findings.append({'rule': 'unreachable-statement', 'path': record['path'], 'line': statement.lineno,
                                                     'methodology': 'statement follows unconditional return/raise/break/continue in the same block'})
                                terminated |= isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue))
            except (SyntaxError, RecursionError):
                pass
    return {'metrics': metrics, 'findings': findings, 'duplicate_candidates': [v for v in clones.values() if len(v) > 1],
            'thresholds': THRESHOLDS, 'methodology': {
                'cyclomatic_syntax': '1 + syntactic branches and logical operators, excluding nested callable bodies; not a full control-flow graph',
                'cognitive_nesting': 'sum(1 + control nesting) for branches, plus logical operators; Shark metric, not Sonar cognitive complexity',
                'duplicates': 'function syntax with identifiers normalized; candidates only, not proven semantic equivalence',
                'unreachable': 'Python statements after an unconditional terminal statement in the same block'},
            'limitations': ['No whole-program dead-code proof, calibrated maintainability score or debt-time estimate.']}
