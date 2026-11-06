"""Bundled syntax extraction. Inputs are immutable text; project code is never imported."""
from __future__ import annotations

import ast
import hashlib
import importlib
import re
from collections import OrderedDict
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
    '.kt': ('kotlin', 'tree_sitter_kotlin', 'language'),
    '.kts': ('kotlin', 'tree_sitter_kotlin', 'language'),
    '.php': ('php', 'tree_sitter_php', 'language_php'),
    '.scala': ('scala', 'tree_sitter_scala', 'language'),
    '.lua': ('lua', 'tree_sitter_lua', 'language'),
    '.sh': ('bash', 'tree_sitter_bash', 'language'),
    '.bash': ('bash', 'tree_sitter_bash', 'language'),
    '.zig': ('zig', 'tree_sitter_zig', 'language'),
}
SYMBOL_KINDS = {
    'function_definition': 'function', 'function_declaration': 'function', 'function_item': 'function',
    'function_declarator': 'function', 'generator_function_declaration': 'function',
    'method_definition': 'method', 'method_declaration': 'method', 'method': 'method', 'singleton_method': 'method',
    'class': 'class', 'class_definition': 'class', 'class_declaration': 'class', 'class_specifier': 'class',
    'object_definition': 'class',
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
COGNITIVE_FLOW_BREAKS = {'else_clause', 'elif_clause', 'except_clause', 'catch_clause', 'continue_statement', 'break_statement', 'goto_statement'}
COMMENT_TYPES = {'comment', 'line_comment', 'block_comment'}
CODE_EXTENSIONS = set(LANGUAGES) | {'.vue', '.svelte', '.swift', '.sql', '.ipynb'}
ENV_PATTERNS = [r'process\.env\.([A-Za-z_]\w*)', r'process\.env\[[\'\"]([A-Za-z_]\w*)[\'\"]\]',
                r'(?:os\.getenv|os\.environ\.get|env::var|std::env::var|os\.Getenv)\s*\(\s*[\'\"]([^\'\"]+)',
                r'os\.environ\s*\[\s*[\'\"]([^\'\"]+)']

# Incremental tree cache keyed by path -> (bytes_data, tree)
_TREE_CACHE: OrderedDict[str, tuple[bytes, object]] = OrderedDict()
_PARSER_CACHE: dict[tuple[str, str], object] = {}


def _id(path, kind, name, start):
    return hashlib.sha256(f'{path}:{kind}:{name}:{start}'.encode()).hexdigest()[:24]


def _get_parser(spec):
    key = (spec[1], spec[2])
    parser = _PARSER_CACHE.get(key)
    if parser is not None:
        return parser
    from tree_sitter import Language, Parser
    grammar = getattr(importlib.import_module(spec[1]), spec[2])()
    parser = Parser(Language(grammar))
    _PARSER_CACHE[key] = parser
    return parser


def _parse_tree_incremental(parser, path: str, data: bytes):
    """Use Tree-sitter incremental parsing when a prior tree for the same path exists."""
    prev = _TREE_CACHE.get(path)
    if prev is not None and prev[0] == data:
        _TREE_CACHE.move_to_end(path)
        return prev[1], True
    tree = parser.parse(data)
    _TREE_CACHE[path] = (data, tree)
    if len(_TREE_CACHE) > 512:
        _TREE_CACHE.popitem(last=False)
    return tree, False


def _extract_doc_comment(lines: list[str], start_line: int) -> str:
    """Extract preceding JSDoc / Rustdoc / Javadoc / comment block above 1-based start_line."""
    idx = start_line - 2
    collected = []
    in_block = False
    while idx >= 0 and len(collected) < 25:
        raw = lines[idx].strip()
        if not raw:
            if collected:
                break
            idx -= 1
            continue
        if raw.startswith(('@', '#[')):
            idx -= 1
            continue
        if raw.endswith('*/'):
            in_block = True
            cleaned = re.sub(r'^/\*\*?|\*/$', '', raw).strip('* ').strip()
            if cleaned:
                collected.append(cleaned)
            if raw.startswith('/*'):
                break
            idx -= 1
            continue
        if in_block:
            cleaned = re.sub(r'^/\*\*?', '', raw).lstrip('* ').strip()
            if cleaned:
                collected.append(cleaned)
            if raw.startswith('/*'):
                break
            idx -= 1
            continue
        if raw.startswith(('///', '//!', '//', '#')) and not raw.startswith('#!'):
            cleaned = re.sub(r'^(?:///|//!|//|#)\s?', '', raw).strip()
            if cleaned:
                collected.append(cleaned)
            idx -= 1
            continue
        break
    return '\n'.join(reversed(collected))[:1200]


def _classify_side_effects(body_text: str) -> list[str]:
    effects = []
    if re.search(r'\b(open|read_text|write_text|write_bytes|unlink|mkdir|rmtree|copytree|fs\.|readFile|writeFile|std::fs)\b', body_text):
        effects.append('filesystem_io')
    if re.search(r'\b(urlopen|urllib|fetch|axios|httpx|requests\.|WebSocket|socket|http\.server)\b', body_text):
        effects.append('network_io')
    if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE|CREATE\s+TABLE|\.execute|executemany|sqlite|cursor)\b', body_text, re.I):
        effects.append('database_access')
    if re.search(r'\b(subprocess\.|Popen|os\.system|exec_command|Command::new|child_process)\b', body_text):
        effects.append('process_execution')
    if re.search(r'\b(raise\s+\w+|throw\s+new|panic!)\b', body_text):
        effects.append('raises_error')
    if re.search(r'\b(self\.\w+\s*=|this\.\w+\s*=|\.append\(|\.pop\(|\.update\(|set\s*\()\b', body_text):
        effects.append('state_mutation')
    return effects or ['pure_or_local']


def _extract_contracts(path: str, text: str) -> list[dict]:
    """Extract IPC, RPC, HTTP route, Tauri command and MCP tool contracts."""
    contracts = []
    # TypeScript/JS backend requests: request('method') or request<...>('method')
    for m in re.finditer(r'\brequest(?:\s*<[^>]+>)?\s*\(\s*[\'\"]([a-z0-9_/-]+)[\'\"]', text):
        contracts.append({'kind': 'rpc_call', 'name': m[1], 'endpoint': m[1], 'path': path, 'line': text.count('\n', 0, m.start()) + 1})
    # Tauri invoke('cmd') and #[tauri::command] fn cmd
    for m in re.finditer(r'\binvoke(?:\s*<[^>]+>)?\s*\(\s*[\'\"]([a-z0-9_]+)[\'\"]', text):
        contracts.append({'kind': 'tauri_invoke', 'name': m[1], 'endpoint': m[1], 'path': path, 'line': text.count('\n', 0, m.start()) + 1})
    for m in re.finditer(r'#\[tauri::command[^\]]*\]\s*(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z0-9_]+)', text):
        contracts.append({'kind': 'tauri_command', 'name': m[1], 'endpoint': m[1], 'path': path, 'line': text.count('\n', 0, m.start()) + 1})
    # Python Service method dispatch: method == "x/y"
    for m in re.finditer(r'\bmethod\s*==\s*[\'\"]([a-z0-9_]+/[a-z0-9_/-]+)[\'\"]', text):
        contracts.append({'kind': 'rpc_handler', 'name': m[1], 'endpoint': m[1], 'path': path, 'line': text.count('\n', 0, m.start()) + 1})
    # HTTP routes (@app.get('/path'), router.post('/path'))
    for m in re.finditer(r'(?:@|\b)(?:app|router|server)\.(get|post|put|delete|patch|route)\s*\(\s*[\'\"](/[^\'\"]*)[\'\"]', text, re.I):
        contracts.append({'kind': 'http_route', 'method': m[1].upper(), 'name': m[2], 'endpoint': m[2], 'path': path, 'line': text.count('\n', 0, m.start()) + 1})
    return contracts[:200]


def _extract_sql(path: str, text: str) -> dict:
    """Parse SQL files and embedded SQL DDL/DML using bundled sqlglot."""
    suffix = PurePosixPath(path).suffix.lower()
    snippets = []
    if suffix == '.sql':
        snippets.append((1, text))
    else:
        for m in re.finditer(r'[\'\"]{1,3}\s*((?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+(?:TABLE|VIRTUAL\s+TABLE|INDEX|VIEW)|ALTER\s+TABLE|DROP\s+TABLE)\b[\s\S]{6,800}?)[\'\"]{1,3}', text, re.I):
            snippets.append((text.count('\n', 0, m.start()) + 1, m[1]))
    if not snippets:
        return {'tables': [], 'ddl': [], 'queries': [], 'errors': []}
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError:
        return {'tables': [], 'ddl': [], 'queries': [], 'errors': []}
    tables, ddl, queries, errors = set(), [], [], []
    for line, sql_text in snippets[:60]:
        cleaned = re.sub(r'\bUSING\s+fts5\s*\([^)]*\)', '(body TEXT)', sql_text, flags=re.I)
        try:
            statements = sqlglot.parse(cleaned)
        except Exception as exc:
            if suffix == '.sql':
                errors.append({'path': path, 'line': line, 'message': str(exc)[:200]})
            continue
        for stmt in statements:
            if stmt is None:
                continue
            stmt_tables = sorted({t.name for t in stmt.find_all(exp.Table) if getattr(t, 'name', None)})
            tables.update(stmt_tables)
            if isinstance(stmt, exp.Create):
                cols = []
                schema = stmt.this if isinstance(stmt.this, exp.Schema) else None
                tname = (schema.this.name if schema and getattr(schema, 'this', None) else getattr(stmt.this, 'name', '')) or (stmt_tables[0] if stmt_tables else '')
                if schema:
                    for col in schema.expressions:
                        if isinstance(col, exp.ColumnDef):
                            dtype = col.args.get('kind')
                            not_null = any(isinstance(c.kind, exp.NotNullColumnConstraint) for c in col.constraints)
                            has_default = any(isinstance(c.kind, exp.DefaultColumnConstraint) for c in col.constraints)
                            cols.append({'name': col.name, 'type': dtype.sql() if dtype else 'ANY', 'not_null': not_null, 'has_default': has_default})
                if tname:
                    ddl.append({'op': 'create_table', 'table': tname, 'columns': cols, 'path': path, 'line': line})
            elif isinstance(stmt, exp.Drop):
                tname = stmt_tables[0] if stmt_tables else ''
                ddl.append({'op': 'drop_table', 'table': tname, 'path': path, 'line': line})
            elif isinstance(stmt, exp.Alter):
                tname = stmt_tables[0] if stmt_tables else ''
                actions = [a.sql() for a in (stmt.args.get('actions') or [])]
                ddl.append({'op': 'alter_table', 'table': tname, 'actions': actions, 'path': path, 'line': line})
            else:
                queries.append({'kind': stmt.key, 'tables': stmt_tables, 'path': path, 'line': line})
    return {'tables': sorted(tables), 'ddl': ddl, 'queries': queries[:100], 'errors': errors}


def parse(path: str, text: str) -> dict:
    if path.lower().endswith('.ipynb'):
        from .notebook_source import project, locate
        try:
            source, cells, language, limitations = project(text)
            result = parse(path + ('.py' if language.lower() in {'python', 'python3'} else '.txt'), source)
            def remap(value):
                if isinstance(value, dict):
                    if value.get('path') == path + '.py' or value.get('path') == path + '.txt': value['path'] = path
                    if type(value.get('line')) is int: value.update(locate(cells, value['line']))
                    for child in value.values(): remap(child)
                elif isinstance(value, list):
                    for child in value: remap(child)
            remap(result)
            result.update(path=path, notebook_cells=cells, notebook_limitations=limitations, analysis_source=source,
                          bytes=len(text.encode()), sha256=hashlib.sha256(text.encode()).hexdigest()[:24])
            return result
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            result = parse(path + '.txt', '')
            result.update(path=path, syntax_errors=[{'line': 1, 'kind': 'invalid_notebook', 'message': str(exc)[:150]}])
            return result
    suffix = PurePosixPath(path).suffix.lower()
    spec = LANGUAGES.get(suffix)
    result = {'path': path, 'language': spec[0] if spec else suffix.lstrip('.') or 'text',
              'symbols': [], 'imports': [], 'calls': [], 'environment': [], 'metrics': [],
              'syntax_errors': [], 'duplicates': [], 'contracts': _extract_contracts(path, text),
              'sql': _extract_sql(path, text),
              'parser': 'unsupported', 'incremental_reused': False, 'truncated': False,
              'lines': len(text.splitlines()), 'bytes': len(text.encode()),
              'sha256': hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()[:24]}
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
    try:
        parser = _get_parser(spec)
        data = text.encode()
        tree, reused = _parse_tree_incremental(parser, path, data)
        result['incremental_reused'] = reused
    except (ImportError, AttributeError, ValueError) as exc:
        result['parser_error'] = type(exc).__name__
        return result
    result['parser'] = 'tree-sitter'
    source_lines = text.splitlines()
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
            params_node = (node.child_by_field_name('parameters') or node.child_by_field_name('formal_parameters')
                           or (initializer.child_by_field_name('parameters') if initializer else None))
            ret_node = (node.child_by_field_name('return_type') or node.child_by_field_name('result')
                        or (initializer.child_by_field_name('return_type') if initializer else None))
            param_text = value(params_node)[:240] if params_node else ''
            ret_text = value(ret_node).lstrip(':-> ').strip()[:120] if ret_node else ''
            line_no = node.start_point.row + 1
            end_line = node.end_point.row + 1
            raw_line = source_lines[line_no - 1] if 1 <= line_no <= len(source_lines) else ''
            exported = bool(
                (node.parent and node.parent.type == 'export_statement')
                or re.search(r'\b(export|pub|public)\b', raw_line)
                or (spec[0] == 'python' and not name.startswith('_'))
                or (spec[0] == 'go' and name[:1].isupper())
            )
            doc_comment = _extract_doc_comment(source_lines, line_no) if spec[0] != 'python' else ''
            body_text = value(node)[:8000]
            fields = sorted(set(re.findall(r'\b(?:self|this)\.([A-Za-z_]\w*)', body_text)))[:40] if kind in FUNCTIONS else []
            symbol = {'id': _id(path, kind, qualified, node.start_byte), 'name': name, 'qualified_name': qualified,
                      'kind': kind, 'path': path, 'line': line_no,
                      'end_line': end_line, 'start_byte': node.start_byte, 'end_byte': node.end_byte,
                      'signature': f'{name}{param_text}' + (f' -> {ret_text}' if ret_text else ''),
                      'parameters': [p.strip() for p in param_text.strip('()').split(',') if p.strip()][:20],
                      'return_type': ret_text, 'exported': exported,
                      'is_async': bool(re.search(r'\basync\b', raw_line[:80])),
                      'fields': fields,
                      'side_effects': _classify_side_effects(body_text) if kind in FUNCTIONS else []}
            if doc_comment:
                symbol['doc'] = doc_comment
            result['symbols'].append(symbol)
            if kind in FUNCTIONS:
                metric_item = _metrics(node, symbol, value)
                symbol['complexity'] = metric_item
                result['metrics'].append(metric_item)
                if end_line - line_no >= 4:
                    tok_seq = _token_sequence(node, value)
                    symbol['_token_sequence'] = tok_seq
                    result['duplicates'].append({'symbol_id': symbol['id'], 'path': path, 'line': symbol['line'],
                                                'name': symbol['qualified_name'],
                                                'fingerprint': _shape(node, value),
                                                'normalized_tokens': tok_seq})
            if kind in FUNCTIONS | {'class', 'interface', 'trait', 'type'}:
                scope = qualified
        if node.type in {'call', 'call_expression', 'method_invocation'} and len(result['calls']) < 5000:
            function = node.child_by_field_name('function') or node.child_by_field_name('name')
            args = node.child_by_field_name('arguments')
            if function:
                arity = len(args.named_children) if args else 0
                result['calls'].append({'expression': value(function)[:200], 'line': node.start_point.row + 1,
                                        'scope': scope, 'arity': arity, 'resolution': 'unresolved_syntax'})
        if node.type in {'import_statement', 'export_statement', 'import_spec', 'preproc_include'}:
            source = node.child_by_field_name('source') or node.child_by_field_name('path')
            if source:
                raw_stmt = value(node)
                imported_names = re.findall(r'\b([A-Za-z_]\w*)\b', raw_stmt.split('from')[0]) if 'from' in raw_stmt else []
                imported_names = [n for n in imported_names if n not in {'import', 'export', 'type', 'default', 'as', 'from', 'const', 'let', 'var'}]
                result['imports'].append({'source': value(source).strip('\'\"<>'), 'line': node.start_point.row + 1,
                                          'imported_names': imported_names[:20], 'kind': 'import'})
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
                    result['imports'].extend({'source': a.name, 'asname': a.asname, 'line': node.lineno, 'kind': 'python_import'} for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    source = '.' * node.level + (node.module or '')
                    for alias in node.names:
                        result['imports'].append({'source': source, 'imported': alias.name, 'asname': alias.asname, 'line': node.lineno, 'kind': 'python_import'})
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    for symbol in result['symbols']:
                        if symbol['line'] == node.lineno and symbol['name'] == node.name:
                            doc = (ast.get_docstring(node) or '')[:1200]
                            symbol['doc'] = doc
                            if doc:
                                try:
                                    import docstring_parser
                                    parsed_doc = docstring_parser.parse(doc)
                                    symbol['doc_summary'] = (parsed_doc.short_description or '')[:300]
                                    symbol['doc_params'] = [{'name': p.arg_name, 'type': p.type_name, 'description': (p.description or '')[:200]} for p in parsed_doc.params[:15]]
                                except Exception:
                                    pass
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                symbol['decorators'] = [ast.unparse(d)[:80] for d in node.decorator_list[:8]]
                            elif isinstance(node, ast.ClassDef):
                                symbol['bases'] = [ast.unparse(b)[:80] for b in node.bases[:8]]
        except (SyntaxError, RecursionError):
            pass
    calls_by_scope: dict[str, list[str]] = {}
    for call_item in result['calls']:
        sc = call_item.get('scope') or ''
        if sc:
            calls_by_scope.setdefault(sc, []).append(call_item['expression'])
    for sym in result['symbols']:
        sym['calls'] = calls_by_scope.get(sym['qualified_name'], [])[:30]
    return result


def _metrics(root, symbol, value):
    decisions, cognitive, sonar_cognitive, nesting_max = 0, 0, 0, 0
    func_name = symbol['name']
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
            sonar_cognitive += 1 + depth
        elif node.type in COGNITIVE_FLOW_BREAKS:
            sonar_cognitive += 1
        # Direct recursion adds +1 to standardized cognitive complexity.
        if node.type in {'call', 'call_expression', 'method_invocation'}:
            fn = node.child_by_field_name('function') or node.child_by_field_name('name')
            if fn and value(fn).split('.')[-1] == func_name:
                sonar_cognitive += 1
        # Count explicit logical operators once per expression, not string contents.
        if node.type in {'boolean_operator', 'binary_expression'}:
            operators = [value(c) for c in node.children if not c.is_named]
            logical = sum(op in {'&&', '||', 'and', 'or', '??'} for op in operators)
            decisions += logical
            cognitive += logical
            sonar_cognitive += 1 if logical else 0
        child_depth = depth + (node.type in NESTING)
        nesting_max = max(nesting_max, child_depth)
        stack.extend((child, child_depth) for child in node.named_children)
    return {'symbol_id': symbol['id'], 'name': symbol['qualified_name'], 'path': symbol['path'], 'line': symbol['line'],
            'lines': symbol['end_line'] - symbol['line'] + 1, 'cyclomatic_syntax': 1 + decisions,
            'cognitive_nesting': cognitive, 'cognitive_complexity': sonar_cognitive, 'max_nesting': nesting_max,
            'parameter_count': len(symbol.get('parameters', [])),
            'methodology': 'shark-syntax-v2', 'partial': visited > 100000}


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


def _token_sequence(root, value) -> str:
    """Compact normalized AST token string for Type-2/Type-3 semantic clone similarity."""
    tokens, stack = [], [root]
    while stack and len(tokens) < 400:
        node = stack.pop()
        if node.type in COMMENT_TYPES:
            continue
        if node.child_count:
            if node.is_named:
                tokens.append(node.type[:12])
            stack.extend(reversed(node.children))
        else:
            if 'identifier' in node.type:
                tokens.append('ID')
            elif 'string' in node.type or 'number' in node.type or 'integer' in node.type:
                tokens.append('LIT')
            else:
                tokens.append(value(node)[:8])
    return ' '.join(tokens[:250])
