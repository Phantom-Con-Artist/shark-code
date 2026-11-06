"""Cell-aware notebook source projections; outputs are never treated as executable source."""
import json


def project(text):
    nb = json.loads(text)
    if not isinstance(nb, dict) or nb.get('nbformat') != 4 or not isinstance(nb.get('cells'), list):
        raise ValueError('Expected a version 4 notebook')
    language = nb.get('metadata', {}).get('language_info', {}).get('name') or nb.get('metadata', {}).get('kernelspec', {}).get('language', 'python')
    lines, cells, limitations = [], [], []
    for index, cell in enumerate(nb['cells']):
        source = cell.get('source', '')
        if isinstance(source, list): source = ''.join(source)
        if not isinstance(source, str): raise ValueError('Invalid cell source')
        identity = cell.get('id', f'cell-{index + 1}')
        start = len(lines) + 1
        raw = source.splitlines() or ['']
        code = cell.get('cell_type') == 'code'
        cell_magic = code and source.lstrip().startswith('%%')
        for line in raw:
            if not code or cell_magic or line.lstrip().startswith(('%', '!', '?')):
                lines.append('# ' + line)
            else: lines.append(line)
        cells.append({'cell_id': identity, 'cell_index': index, 'cell_type': cell.get('cell_type'), 'start_line': start, 'end_line': len(lines)})
        lines.append('')
        if cell_magic or any(l.lstrip().startswith(('%', '!', '?')) for l in raw):
            limitations.append({'cell_id': identity, 'reason': 'IPython magics and shell escapes are excluded from Python static analysis.'})
    if language.lower() not in {'python', 'python3'}:
        limitations.append({'reason': f'Kernel language {language} has no notebook syntax projection yet.'})
    return '\n'.join(lines), cells, language, limitations


def locate(cells, line):
    return next(({'cell_id': c['cell_id'], 'cell_index': c['cell_index'], 'cell_line': line - c['start_line'] + 1,
                  'line_kind': 'notebook_projected_source'} for c in cells if c['start_line'] <= line <= c['end_line']), {})
