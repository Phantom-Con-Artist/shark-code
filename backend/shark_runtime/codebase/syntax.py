"""Bundled syntax extraction. Inputs are immutable text; project code is never imported."""
from __future__ import annotations

import ast
import hashlib
import importlib
import re
from pathlib import PurePosixPath

LANGUAGES = {
    '.py': ('python', 'tree_sitter_python', 'language'),
    '.pyi': ('python', 'tree_sitter_python', 'language'),
    '.ts': ('typescript', 'tree_sitter_typescript', 'language_typescript'),
    '.tsx': ('tsx', 'tree_sitter_typescript', 'language_tsx'),
    '.js': ('javascript', 'tree_sitter_javascript', 'language'),
    '.jsx': ('javascript', 'tree_sitter_javascript', 'language'),
    '.mjs': ('javascript', 'tree_sitter_javascript', 'language'),
    '.cjs': ('javascript', 'tree_sitter_javascript', 'language'),
    '.rs': ('rust', 'tree_sitter_rust', 'language'),
    '.go': ('go', 'tree_sitter_go', 'language'),
    '.java': ('java', 'tree_sitter_java', 'language'),
    '.c': ('c', 'tree_sitter_c', 'language'),
    '.h': ('c', 'tree_sitter_c', 'language'),
    '.cpp': ('cpp', 'tree_sitter_cpp', 'language'),
    '.hpp': ('cpp', 'tree_sitter_cpp', 'language'),
    '.cs': ('csharp', 'tree_sitter_c_sharp', 'language'),
    '.rb': ('ruby', 'tree_sitter_ruby', 'language'),
}
SYMBOL_KINDS = {
    'function_definition': 'function', 'function_declaration': 'function', 'function_item': 'function',
    'function_declarator': 'function', 'generator_function_declaration': 'function',
    'method_definition': 'method', 'method_declaration': 'method', 'method': 'method', 'singleton_method': 'method',
    'class': 'class', 'class_definition': 'class', 'class_declaration': 'class', 'class_specifier': 'class',
    'interface_declaration': 'interface', 'trait_item': 'trait', 'struct_item': 'type',
    'struct_specifier': 'type', 'enum_item': 'type', 'enum_declaration': 'type',
    'type_item': 'type', 'type_alias_declaration': 'type', 'type_spec': 'type',
    'variable_declarator': 'variable', 'const_item': 'variable', 'static_item': 'variable',
    'assignment': 'variable', 'let_declaration': 'variable', 'short_var_declaration': 'variable',
}
FUNCTIONS = {'function', 'method'}
DECISIONS = {'if_statement', 'if_expression', 'for_statement', 'for_expression', 'for_in_statement',
             'while_statement', 'while_expression', 'do_statement', 'case_statement', 'switch_case',
             'except_clause', 'catch_clause', 'conditional_expression', 'ternary_expression', 'match_arm'}
NESTING = DECISIONS - {'conditional_expression', 'ternary_expression', 'match_arm'}
COMMENT_TYPES = {'comment', 'line_comment', 'block_comment'}
CODE_EXTENSIONS = set(LANGUAGES) | {'.vue', '.svelte', '.swift', '.kt', '.php', '.scala', '.sh', '.sql'}
ENV_PATTERNS = [r'process\.env\.([A-Za-z_]\w*)', r'process\.env\[[\'\"]([A-Za-z_]\w*)[\'\"]\]',
                r'(?:os\.getenv|os\.environ\.get|env::var|std::env::var|os\.Getenv)\s*\(\s*[\'\"]([^\'\"]+)',
                r'os\.environ\s*\[\s*[\'\"]([^\'\"]+)']


def _id(path, kind, name, start):
    return hashlib.sha256(f'{path}:{kind}:{name}:{start}'.encode()).hexdigest()[:24]


def parse(path: str, text: str) -> dict:
    suffix = PurePosixPath(path).suffix.lower()
    spec = LANGUAGES.get(suffix)
    result = {'path': path, 'language': spec[0] if spec else suffix.lstrip('.') or 'text',
              'symbols': [], 'imports': [], 'calls': [], 'environment': [], 'metrics': [],
              'syntax_errors': [], 'duplicates': [], 'parser': 'unsupported', 'truncated': False,
              'lines': len(text.splitlines()), 'bytes': len(text.encode())}
    for pattern in ENV_PATTERNS:
        for match in re.finditer(pattern, text):
            result['environment'].append({'name': match[1], 'path': path, 'line': text.count('\n', 0, match.start()) + 1,
                                          'resolution': 'syntax_pattern'})
    if suffix in {'.html', '.htm'}:
        for match in re.finditer(r'<(?:script|link)\b[^>]*?(?:src|href)=[\'\"]([^\'\"]+)', text, re.I):
            if not re.match(r'^(?:[a-z]+:|//|#)', match[1], re.I):
                result['imports'].append({'source': match[1], 'line': text.count('\n', 0, match.start()) + 1,
                                          'kind': 'html_resource'})
    if not spec:
        return result
    from tree_sitter import Language, Parser
    try:
        grammar = getattr(importlib.import_module(spec[1]), spec[2])()
        tree = Parser(Language(grammar)).parse(text.encode())
    except (ImportError, AttributeError, ValueError) as exc:
        result['parser_error'] = type(exc).__name__
        return result
    result['parser'] = 'tree-sitter'
    data = text.encode()
    def value(node):
        return data[node.start_byte:node.end_byte].decode('utf-8', errors='replace')
    stack = [(tree.root_node, '')]
    visits = 0
    while stack:
        node, scope = stack.pop()
        visits += 1
        if visits > 150000 or len(result['symbols']) >= 2000:
            result['truncated'] = True
            break
        if node.is_error or node.is_missing:
            if len(result['syntax_errors']) < 50:
                result['syntax_errors'].append({'line': node.start_point.row + 1, 'kind': node.type})
        kind = SYMBOL_KINDS.get(node.type)
        name_node = node.child_by_field_name('name')
        if node.type == 'assignment':
            name_node = node.child_by_field_name('left')
        elif node.type == 'let_declaration':
            name_node = node.child_by_field_name('pattern')
        elif node.type == 'short_var_declaration':
            name_node = node.child_by_field_name('left')
        if kind and name_node is None and node.type in {'function_definition', 'function_declarator'}:
            name_node = node.child_by_field_name('declarator')
            while name_node is not None and name_node.type not in {'identifier', 'field_identifier', 'qualified_identifier'}:
                name_node = name_node.child_by_field_name('declarator')
        if kind == 'function' and spec[0] == 'python':
            ancestor = node.parent
            while ancestor is not None and ancestor.type in {'block', 'decorated_definition'}:
                ancestor = ancestor.parent
            if ancestor is not None and ancestor.type == 'class_definition':
                kind = 'method'
        # A JS variable initialized with a function is itself a callable symbol.
        initializer = node.child_by_field_name('value')
        if node.type == 'variable_declarator' and initializer and initializer.type in {'arrow_function', 'function_expression'}:
            kind = 'function'
        if node.type == 'function_declarator' and node.parent and node.parent.type == 'function_definition':
            kind = None
        if kind and name_node:
            name = value(name_node)[:200]
            qualified = f'{scope}.{name}' if scope else name
            symbol = {'id': _id(path, kind, qualified, node.start_byte), 'name': name, 'qualified_name': qualified,
                      'kind': kind, 'path': path, 'line': node.start_point.row + 1,
                      'end_line': node.end_point.row + 1, 'start_byte': node.start_byte, 'end_byte': node.end_byte}
            result['symbols'].append(symbol)
            if kind in FUNCTIONS:
                result['metrics'].append(_metrics(node, symbol, value))
                if node.end_point.row - node.start_point.row >= 4:
                    result['duplicates'].append({'symbol_id': symbol['id'], 'path': path, 'line': symbol['line'],
                                                'fingerprint': _shape(node, value)})
            if kind in FUNCTIONS | {'class', 'interface', 'trait', 'type'}:
                scope = qualified
        if node.type in {'call', 'call_expression', 'method_invocation'} and len(result['calls']) < 5000:
            function = node.child_by_field_name('function') or node.child_by_field_name('name')
            if function:
                result['calls'].append({'expression': value(function)[:200], 'line': node.start_point.row + 1,
                                        'scope': scope, 'resolution': 'unresolved_syntax'})
        if node.type in {'import_statement', 'export_statement', 'import_spec', 'preproc_include'}:
            source = node.child_by_field_name('source') or node.child_by_field_name('path')
            if source:
                result['imports'].append({'source': value(source).strip('\'\"<>'), 'line': node.start_point.row + 1,
                                          'kind': 'import'})
        if node.type in {'use_declaration', 'mod_item'}:
            source = node.child_by_field_name('argument') or node.child_by_field_name('name')
            if source:
                result['imports'].append({'source': value(source), 'line': node.start_point.row + 1, 'kind': 'rust_use'})
        if node.type == 'call_expression':
            function = node.child_by_field_name('function')
            args = node.child_by_field_name('arguments')
            if function and args and value(function) in {'require', 'import'} and args.named_children:
                arg = args.named_children[0]
                if arg.type in {'string', 'string_literal'}:
                    result['imports'].append({'source': value(arg).strip('\'\"'), 'line': node.start_point.row + 1, 'kind': 'import'})
        stack.extend((child, scope) for child in reversed(node.named_children))
    if suffix in {'.py', '.pyi'}:
        try:
            module = ast.parse(text)
            result['imports'] = []
            for node in ast.walk(module):
                if isinstance(node, ast.Import):
                    result['imports'].extend({'source': a.name, 'line': node.lineno, 'kind': 'python_import'} for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    source = '.' * node.level + (node.module or '')
                    for alias in node.names:
                        result['imports'].append({'source': source, 'imported': alias.name, 'line': node.lineno, 'kind': 'python_import'})
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    for symbol in result['symbols']:
                        if symbol['line'] == node.lineno and symbol['name'] == node.name:
                            symbol['doc'] = (ast.get_docstring(node) or '')[:1200]
        except (SyntaxError, RecursionError):
            pass
    return result


def _metrics(root, symbol, value):
    decisions, cognitive, nesting_max = 0, 0, 0
    stack = [(root, 0)]
    visited = 0
    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > 100000:
            break
        if node != root and SYMBOL_KINDS.get(node.type) in FUNCTIONS | {'class'}:
            continue
        decision = node.type in DECISIONS
        if decision:
            decisions += 1
            cognitive += 1 + depth
        # Count explicit logical operators once per expression, not string contents.
        if node.type in {'boolean_operator', 'binary_expression'}:
            operators = [value(c) for c in node.children if not c.is_named]
            logical = sum(op in {'&&', '||', 'and', 'or', '??'} for op in operators)
            decisions += logical
            cognitive += logical
        child_depth = depth + (node.type in NESTING)
        nesting_max = max(nesting_max, child_depth)
        stack.extend((child, child_depth) for child in node.named_children)
    return {'symbol_id': symbol['id'], 'name': symbol['qualified_name'], 'path': symbol['path'], 'line': symbol['line'],
            'lines': symbol['end_line'] - symbol['line'] + 1, 'cyclomatic_syntax': 1 + decisions,
            'cognitive_nesting': cognitive, 'max_nesting': nesting_max,
            'methodology': 'shark-syntax-v1', 'partial': visited > 100000}


def _shape(root, value):
    # Syntax-normalized clone candidates, never a claim of equivalent business behavior.
    tokens, stack = [], [root]
    while stack and len(tokens) < 30000:
        node = stack.pop()
        if node.type in COMMENT_TYPES:
            continue
        if node.child_count:
            tokens.append(node.type)
            stack.extend(reversed(node.children))
        else:
            tokens.append('_id' if 'identifier' in node.type else f'{node.type}:{value(node)}')
    return hashlib.sha256('\x1f'.join(tokens).encode()).hexdigest()
