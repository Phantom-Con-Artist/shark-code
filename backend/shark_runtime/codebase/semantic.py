"""Bundled semantic, architectural, change-impact, and agent-workflow intelligence."""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

import networkx as nx
import numpy as np
from rapidfuzz import fuzz

DOMAIN_SYNONYMS: dict[str, list[str]] = {
    'auth': ['authentication', 'authorize', 'authorization', 'login', 'token', 'session', 'permission', 'credential', 'jwt', 'oauth'],
    'security': ['vulnerability', 'taint', 'sanitize', 'escape', 'secret', 'injection', 'xss', 'csrf', 'audit', 'unsafe'],
    'database': ['sql', 'sqlite', 'query', 'schema', 'table', 'migration', 'persistence', 'store', 'repository', 'transaction'],
    'network': ['http', 'fetch', 'request', 'response', 'socket', 'rpc', 'ipc', 'endpoint', 'route', 'api', 'client'],
    'workflow': ['automata', 'orchestration', 'pipeline', 'graph', 'node', 'edge', 'trigger', 'step', 'execution', 'dispatch'],
    'parser': ['syntax', 'ast', 'treesitter', 'grammar', 'token', 'lexical', 'symbol', 'compile'],
    'dependency': ['manifest', 'lockfile', 'package', 'version', 'semver', 'license', 'sbom', 'advisory'],
    'performance': ['latency', 'bottleneck', 'profile', 'memory', 'cache', 'async', 'concurrency', 'hotspot', 'loop'],
    'testing': ['test', 'assert', 'fixture', 'mock', 'verify', 'check', 'coverage', 'regression'],
    'ui': ['component', 'view', 'panel', 'modal', 'dock', 'canvas', 'button', 'render', 'state', 'store'],
}

STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'are', 'was', 'were', 'have', 'has',
    'had', 'not', 'but', 'you', 'all', 'any', 'can', 'her', 'his', 'its', 'our', 'out', 'who',
    'get', 'set', 'def', 'var', 'let', 'const', 'function', 'return', 'import', 'export', 'class',
    'self', 'true', 'false', 'none', 'null', 'void', 'int', 'str', 'bool', 'dict', 'list', 'new',
}


def split_identifier(text: str) -> list[str]:
    if not text:
        return []
    # Split camelCase, PascalCase, snake_case, kebab-case, and paths
    spaced = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    spaced = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', spaced)
    tokens = re.findall(r'[A-Za-z][A-Za-z0-9]*', spaced.lower())
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]


def expand_query_concepts(tokens: list[str]) -> list[str]:
    expanded = list(tokens)
    for tok in list(tokens):
        for concept, synonyms in DOMAIN_SYNONYMS.items():
            if tok == concept or tok in synonyms:
                expanded.append(concept)
                expanded.extend(synonyms[:4])
    return expanded


def semantic_search(
    parsed_files: dict[str, dict],
    sources: dict[str, str],
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Local dense concept + latent semantic SVD search over files and symbols."""
    query_tokens = split_identifier(query)
    if not query_tokens:
        return {
            'query': query,
            'embedding_model': 'shark-local-lsa-v1',
            'expanded_concepts': [],
            'matches': [],
        }

    expanded_tokens = expand_query_concepts(query_tokens)
    docs: list[dict[str, Any]] = []
    doc_tokens_list: list[Counter[str]] = []
    vocab_df: Counter[str] = Counter()

    for path, item in sorted(parsed_files.items()):
        path_tokens = split_identifier(path)
        file_syms = item.get('symbols', [])
        if file_syms:
            for sym in file_syms:
                sym_tokens = (
                    split_identifier(sym.get('name', '')) * 3
                    + split_identifier(sym.get('qualified_name', '')) * 2
                    + split_identifier(sym.get('signature', ''))
                    + split_identifier(sym.get('doc', '')) * 2
                    + split_identifier(' '.join(sym.get('calls', [])[:15]))
                    + split_identifier(' '.join(sym.get('side_effects', [])))
                    + path_tokens
                )
                if not sym_tokens:
                    continue
                counts = Counter(sym_tokens)
                for w in counts:
                    vocab_df[w] += 1
                docs.append({
                    'kind': sym.get('kind', 'symbol'),
                    'path': path,
                    'name': sym.get('qualified_name') or sym.get('name'),
                    'line': sym.get('line', 1),
                    'end_line': sym.get('end_line', sym.get('line', 1)),
                    'signature': sym.get('signature'),
                    'doc_summary': sym.get('doc_summary') or sym.get('doc', ''),
                    'side_effects': sym.get('side_effects', []),
                })
                doc_tokens_list.append(counts)
        else:
            raw_text = sources.get(path, '')[:4000]
            file_tokens = path_tokens * 3 + split_identifier(raw_text)
            if not file_tokens:
                continue
            counts = Counter(file_tokens)
            for w in counts:
                vocab_df[w] += 1
            docs.append({
                'kind': 'file',
                'path': path,
                'name': PurePosixPath(path).name,
                'line': 1,
                'end_line': item.get('lines', 1),
                'signature': path,
                'doc_summary': '',
                'side_effects': [],
            })
            doc_tokens_list.append(counts)

    if not docs:
        return {
            'query': query,
            'embedding_model': 'shark-local-lsa-v1',
            'expanded_concepts': sorted(set(expanded_tokens)),
            'matches': [],
        }

    # Build top vocabulary including query terms
    query_counts = Counter(expanded_tokens)
    for t in query_tokens:
        query_counts[t] += 2
    vocab = sorted(set(query_counts.keys()) | {w for w, _ in vocab_df.most_common(1200)})
    word_to_idx = {w: idx for idx, w in enumerate(vocab)}
    n_docs = len(docs)
    n_vocab = len(vocab)

    idf = np.ones(n_vocab, dtype=np.float32)
    for w, idx in word_to_idx.items():
        idf[idx] = math.log((1.0 + n_docs) / (1.0 + vocab_df.get(w, 0))) + 1.0

    matrix = np.zeros((n_docs, n_vocab), dtype=np.float32)
    for d_idx, counts in enumerate(doc_tokens_list):
        for w, c in counts.items():
            v_idx = word_to_idx.get(w)
            if v_idx is not None:
                matrix[d_idx, v_idx] = (1.0 + math.log(c)) * idf[v_idx]

    q_vec = np.zeros(n_vocab, dtype=np.float32)
    for w, c in query_counts.items():
        v_idx = word_to_idx.get(w)
        if v_idx is not None:
            q_vec[v_idx] = (1.0 + math.log(c)) * idf[v_idx]

    # Normalize TF-IDF vectors
    doc_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    doc_norms[doc_norms == 0] = 1.0
    norm_matrix = matrix / doc_norms
    q_norm = np.linalg.norm(q_vec)
    norm_q = q_vec / (q_norm if q_norm > 0 else 1.0)
    direct_scores = norm_matrix @ norm_q

    # Latent Semantic SVD projection for conceptual similarity when enough docs exist
    lsa_scores = direct_scores
    if n_docs >= 4 and n_vocab >= 4:
        try:
            k = min(24, n_docs - 1, n_vocab - 1)
            if k >= 2:
                u, s, vt = np.linalg.svd(norm_matrix, full_matrices=False)
                u_k = u[:, :k] * s[:k]
                q_k = norm_q @ vt[:k, :].T
                u_norms = np.linalg.norm(u_k, axis=1)
                u_norms[u_norms == 0] = 1.0
                qk_norm = np.linalg.norm(q_k)
                if qk_norm > 0:
                    lsa_cosine = (u_k @ q_k) / (u_norms * qk_norm)
                    lsa_scores = 0.65 * direct_scores + 0.35 * np.clip(lsa_cosine, 0.0, 1.0)
        except Exception:
            lsa_scores = direct_scores

    ranked_indices = np.argsort(-lsa_scores)
    matches = []
    for idx in ranked_indices[: max(limit * 2, 20)]:
        score = float(lsa_scores[idx])
        if score <= 0.02:
            continue
        doc = docs[int(idx)]
        matched_terms = sorted(set(expanded_tokens) & set(doc_tokens_list[int(idx)].keys()))
        matches.append({
            **doc,
            'semantic_score': round(score, 4),
            'matched_concepts': matched_terms[:8],
            'evidence': 'latent_semantic_embedding' if not (set(query_tokens) & set( matched_terms)) else 'concept_and_lexical_embedding',
        })
        if len(matches) >= limit:
            break

    return {
        'query': query,
        'embedding_model': 'shark-local-lsa-v1',
        'expanded_concepts': sorted(set(expanded_tokens) - set(query_tokens))[:12],
        'matches': matches,
    }


def extract_domain_concepts(parsed_files: dict[str, dict]) -> list[dict[str, Any]]:
    """Extract business and technical domain vocabulary clusters across symbols and files."""
    term_files: dict[str, set[str]] = defaultdict(set)
    term_symbols: dict[str, list[str]] = defaultdict(list)
    term_freq: Counter[str] = Counter()

    for path, item in sorted(parsed_files.items()):
        for sym in item.get('symbols', []):
            tokens = split_identifier(sym.get('name', '')) + split_identifier(sym.get('doc_summary', ''))
            for tok in tokens:
                if len(tok) < 3:
                    continue
                term_freq[tok] += 1
                term_files[tok].add(path)
                qname = sym.get('qualified_name') or sym.get('name')
                if qname and len(term_symbols[tok]) < 6 and qname not in term_symbols[tok]:
                    term_symbols[tok].append(qname)

    concepts = []
    for term, count in term_freq.most_common(25):
        domain_group = 'general'
        for group, syns in DOMAIN_SYNONYMS.items():
            if term == group or term in syns:
                domain_group = group
                break
        concepts.append({
            'concept': term,
            'domain': domain_group,
            'occurrences': count,
            'file_count': len(term_files[term]),
            'files': sorted(term_files[term])[:6],
            'sample_symbols': term_symbols[term][:5],
        })
    return concepts


def detect_semantic_duplicates(parsed_files: dict[str, dict], min_lines: int = 5) -> list[dict[str, Any]]:
    """Detect Type-1 (exact), Type-2 (renamed identifier), and Type-3 (near-miss) clones across functions."""
    candidates = []
    for path, item in sorted(parsed_files.items()):
        for sym in item.get('symbols', []):
            if sym.get('kind') not in {'function', 'method'}:
                continue
            span = int(sym.get('end_line', sym.get('line', 1))) - int(sym.get('line', 1)) + 1
            tok_seq = sym.get('_token_sequence') or ''
            if span >= min_lines and len(tok_seq.split()) >= 12:
                candidates.append({
                    'path': path,
                    'name': sym.get('qualified_name') or sym.get('name'),
                    'line': sym.get('line', 1),
                    'end_line': sym.get('end_line', sym.get('line', 1)),
                    'tokens': tok_seq,
                    'calls': tuple(sorted(sym.get('calls', [])[:10])),
                })

    clones = []
    seen_pairs = set()
    # Group exact Type-2 structural clones first
    by_tokens: dict[str, list[dict]] = defaultdict(list)
    for cand in candidates:
        by_tokens[cand['tokens']].append(cand)

    for tok_seq, group in by_tokens.items():
        if len(group) > 1:
            clones.append({
                'clone_type': 'Type-2 (structural AST match)',
                'similarity': 1.0,
                'locations': [
                    {'path': g['path'], 'symbol': g['name'], 'line': g['line'], 'end_line': g['end_line']}
                    for g in group[:6]
                ],
            })
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    seen_pairs.add(((group[i]['path'], group[i]['line']), (group[j]['path'], group[j]['line'])))

    # Check near-miss Type-3 clones with rapidfuzz on capped candidate list
    capped = candidates[:120]
    for i in range(len(capped)):
        for j in range(i + 1, len(capped)):
            a, b = capped[i], capped[j]
            pair_key = ((a['path'], a['line']), (b['path'], b['line']))
            if pair_key in seen_pairs:
                continue
            len_a, len_b = len(a['tokens']), len(b['tokens'])
            if min(len_a, len_b) / max(len_a, len_b, 1) < 0.75:
                continue
            sim = fuzz.ratio(a['tokens'], b['tokens']) / 100.0
            if sim >= 0.86:
                clones.append({
                    'clone_type': 'Type-3 (near-miss structural clone)',
                    'similarity': round(sim, 3),
                    'locations': [
                        {'path': a['path'], 'symbol': a['name'], 'line': a['line'], 'end_line': a['end_line']},
                        {'path': b['path'], 'symbol': b['name'], 'line': b['line'], 'end_line': b['end_line']},
                    ],
                })
                if len(clones) >= 40:
                    return clones
    return clones


def detect_patterns(parsed_files: dict[str, dict]) -> list[dict[str, Any]]:
    """Recognize common architectural and design patterns from AST symbols and structure."""
    patterns = []
    for path, item in sorted(parsed_files.items()):
        symbols = item.get('symbols', [])
        sym_names = [s.get('name', '') for s in symbols]
        for sym in symbols:
            name = sym.get('name', '')
            qname = sym.get('qualified_name') or name
            kind = sym.get('kind', '')
            low = name.lower()
            calls = set(sym.get('calls', []))
            decorators = sym.get('decorators', [])

            if kind == 'class':
                if 'singleton' in low or '_instance' in sym.get('fields', []):
                    patterns.append({'pattern': 'Singleton', 'path': path, 'symbol': qname, 'line': sym.get('line', 1), 'evidence': 'Instance caching field or Singleton class naming'})
                if low.endswith(('factory', 'builder', 'creator')):
                    patterns.append({'pattern': 'Factory / Builder', 'path': path, 'symbol': qname, 'line': sym.get('line', 1), 'evidence': f'Creational class {qname}'})
                if low.endswith(('repository', 'store', 'dao', 'gateway', 'adapter', 'client')):
                    patterns.append({'pattern': 'Repository / Gateway / Adapter', 'path': path, 'symbol': qname, 'line': sym.get('line', 1), 'evidence': f'Boundary abstraction class {qname}'})
                if low.endswith(('observer', 'listener', 'subscriber', 'bus', 'dispatcher')):
                    patterns.append({'pattern': 'Observer / Event Bus', 'path': path, 'symbol': qname, 'line': sym.get('line', 1), 'evidence': f'Event dispatch/subscription class {qname}'})
            elif kind in {'function', 'method'}:
                if low.startswith(('create_', 'make_', 'build_', 'from_')) and sym.get('return_type'):
                    patterns.append({'pattern': 'Factory Function', 'path': path, 'symbol': qname, 'line': sym.get('line', 1), 'evidence': f'Constructor helper returning {sym.get("return_type")}'})
                if decorators:
                    patterns.append({'pattern': 'Decorator / Aspect', 'path': path, 'symbol': qname, 'line': sym.get('line', 1), 'evidence': f'Decorated with {", ".join(decorators[:3])}'})
                if any(c in calls for c in ('subscribe', 'emit', 'publish', 'dispatch', 'addEventListener')):
                    patterns.append({'pattern': 'Observer / Pub-Sub', 'path': path, 'symbol': qname, 'line': sym.get('line', 1), 'evidence': 'Event emission or subscription call'})
        if any(n.startswith('use') and len(n) > 3 and n[3:4].isupper() for n in sym_names):
            hook_names = [n for n in sym_names if n.startswith('use') and len(n) > 3 and n[3:4].isupper()]
            patterns.append({'pattern': 'React Custom Hook / State Store', 'path': path, 'symbol': hook_names[0], 'line': 1, 'evidence': f'Hook exports: {", ".join(hook_names[:4])}'})
    return patterns[:80]


def behavioral_explanation(
    path: str | None,
    symbol_name: str | None,
    parsed_files: dict[str, dict],
    inbound: dict[str, set[str]],
    outbound: dict[str, set[str]],
) -> dict[str, Any]:
    """Generate an evidence-backed behavioral summary for a symbol or file."""
    if path and path in parsed_files and not symbol_name:
        item = parsed_files[path]
        syms = item.get('symbols', [])
        effects = sorted({eff for s in syms for eff in s.get('side_effects', [])})
        contracts = item.get('contracts', [])
        sql_info = item.get('sql', {})
        summary_parts = [
            f"{path} ({item.get('language')}, {item.get('lines', 0)} lines) defines {len(syms)} symbols.",
        ]
        if effects:
            summary_parts.append(f"Observed side effects: {', '.join(effects)}.")
        if contracts:
            summary_parts.append(f"Cross-boundary contracts: {len(contracts)} RPC/HTTP endpoints or calls.")
        if sql_info.get('tables'):
            summary_parts.append(f"Touches SQL tables: {', '.join(sql_info['tables'])}.")
        return {
            'summary': ' '.join(summary_parts),
            'side_effects': effects,
            'contracts': contracts[:15],
            'sql_tables': sql_info.get('tables', []),
            'inbound_dependents': sorted(inbound.get(path, set())),
            'outbound_dependencies': sorted(outbound.get(path, set())),
        }

    # Symbol-level behavioral summary
    matches = []
    for p, item in sorted(parsed_files.items()):
        if path and p != path:
            continue
        for sym in item.get('symbols', []):
            if symbol_name in {sym.get('name'), sym.get('qualified_name')}:
                matches.append((p, sym))

    if not matches:
        return {'summary': 'No matching symbol or file found in index.', 'side_effects': [], 'contracts': []}

    p, sym = matches[0]
    effects = sym.get('side_effects', [])
    calls = sym.get('calls', [])
    doc = sym.get('doc_summary') or sym.get('doc') or ''
    sig = sym.get('signature') or sym.get('name')
    behavior = [f"`{sig}` in `{p}` (lines {sym.get('line')}-{sym.get('end_line')})"]
    if doc:
        behavior.append(f"Documented purpose: {doc}")
    if calls:
        behavior.append(f"Invokes {len(calls)} operations ({', '.join(calls[:8])}).")
    if effects:
        behavior.append(f"Side effects: {', '.join(effects)}.")
    else:
        behavior.append("Pure/local computation with no external I/O side effects detected.")

    return {
        'summary': ' '.join(behavior),
        'signature': sig,
        'parameters': sym.get('parameters', []),
        'return_type': sym.get('return_type'),
        'doc_summary': doc,
        'doc_params': sym.get('doc_params', []),
        'side_effects': effects,
        'calls': calls[:25],
    }


def identify_subsystems(
    parsed_files: dict[str, dict],
    edges: list[dict],
) -> list[dict[str, Any]]:
    """Group repository modules into cohesive semantic subsystems using graph connectivity and directory hierarchy."""
    g = nx.Graph()
    for path in parsed_files:
        g.add_node(path)
    for edge in edges:
        if edge.get('resolved') and edge.get('source') in parsed_files and edge.get('target') in parsed_files:
            g.add_edge(edge['source'], edge['target'])

    dir_groups: dict[str, list[str]] = defaultdict(list)
    for path in sorted(parsed_files):
        parts = PurePosixPath(path).parts
        if len(parts) >= 2 and parts[0] in {'src', 'backend', 'packages', 'apps', 'crates'}:
            key = '/'.join(parts[:2])
        elif len(parts) >= 1:
            key = parts[0]
        else:
            key = 'root'
        dir_groups[key].append(path)

    subsystems = []
    for name, files in sorted(dir_groups.items()):
        langs = Counter(parsed_files[f].get('language') for f in files)
        symbols_count = sum(len(parsed_files[f].get('symbols', [])) for f in files)
        effects = sorted({eff for f in files for s in parsed_files[f].get('symbols', []) for eff in s.get('side_effects', [])})
        layer = _classify_path_layer(name, files, parsed_files)
        subsystems.append({
            'id': name,
            'layer': layer,
            'file_count': len(files),
            'symbol_count': symbols_count,
            'primary_language': langs.most_common(1)[0][0] if langs else 'unknown',
            'capabilities': effects,
            'sample_files': files[:8],
        })
    return subsystems


def _classify_path_layer(group_name: str, files: list[str], parsed_files: dict[str, dict]) -> str:
    low = group_name.lower()
    if any(k in low for k in ('test', 'spec', '__tests__', 'fixtures')):
        return 'verification_tests'
    if any(k in low for k in ('components', 'views', 'pages', 'ui', 'styles', 'assets')):
        return 'ui_presentation'
    if any(k in low for k in ('stores', 'state', 'hooks')):
        return 'state_management'
    if any(k in low for k in ('api', 'gateway', 'service', 'routes', 'controllers', 'mcp')):
        return 'api_gateway'
    if any(k in low for k in ('automata', 'orchestration', 'workflow', 'agent')):
        return 'orchestration_workflow'
    if any(k in low for k in ('codebase', 'intelligence', 'domain', 'models')):
        return 'domain_intelligence'
    if any(k in low for k in ('db', 'storage', 'migrations', 'sql', 'persistence')):
        return 'persistence_storage'
    if any(k in low for k in ('src-tauri', 'scripts', 'config', 'runtime')):
        return 'infrastructure_runtime'
    # Fallback based on file extensions
    langs = {parsed_files[f].get('language') for f in files if f in parsed_files}
    if langs & {'tsx', 'jsx', 'css', 'html'}:
        return 'ui_presentation'
    return 'application_core'


def infer_layers_and_metrics(
    parsed_files: dict[str, dict],
    inbound: dict[str, set[str]],
    outbound: dict[str, set[str]],
    boundaries: list[dict] | None = None,
) -> dict[str, Any]:
    """Compute architectural layers, Robert C. Martin coupling/instability/abstractness metrics, and layer violations."""
    layer_Rank = {
        'ui_presentation': 1,
        'state_management': 2,
        'api_gateway': 3,
        'orchestration_workflow': 4,
        'domain_intelligence': 5,
        'persistence_storage': 6,
        'infrastructure_runtime': 7,
        'application_core': 4,
        'verification_tests': 0,
    }
    file_layers: dict[str, str] = {}
    layer_files: dict[str, list[str]] = defaultdict(list)
    for path in sorted(parsed_files):
        layer = _classify_path_layer(path, [path], parsed_files)
        file_layers[path] = layer
        layer_files[layer].append(path)

    module_metrics = []
    for path, item in sorted(parsed_files.items()):
        ca = len(inbound.get(path, set()))
        ce = len(outbound.get(path, set()))
        instability = round(ce / (ca + ce), 3) if (ca + ce) > 0 else 0.0
        syms = item.get('symbols', [])
        abstract_syms = sum(
            1 for s in syms
            if s.get('kind') in {'interface', 'type', 'trait', 'enum'}
            or any(b in ('ABC', 'Protocol') for b in s.get('bases', []))
        )
        abstractness = round(abstract_syms / len(syms), 3) if syms else 0.0
        distance = round(abs(abstractness + instability - 1.0), 3)
        zone = 'balanced'
        if distance > 0.7 and instability < 0.3 and abstractness < 0.2 and ca >= 3:
            zone = 'zone_of_pain (rigid concrete dependency)'
        elif distance > 0.7 and instability > 0.7 and abstractness > 0.7:
            zone = 'zone_of_uselessness (unreferenced abstraction)'
        module_metrics.append({
            'path': path,
            'layer': file_layers[path],
            'afferent_coupling_ca': ca,
            'efferent_coupling_ce': ce,
            'instability': instability,
            'abstractness': abstractness,
            'distance_from_main_sequence': distance,
            'zone': zone,
        })

    inferred_layer_violations = []
    for src, targets in sorted(outbound.items()):
        src_layer = file_layers.get(src, 'application_core')
        if src_layer == 'verification_tests':
            continue
        for dst in sorted(targets):
            dst_layer = file_layers.get(dst, 'application_core')
            # Domain or storage importing UI presentation is an architectural inversion
            if src_layer in {'domain_intelligence', 'persistence_storage'} and dst_layer == 'ui_presentation':
                inferred_layer_violations.append({
                    'source': src,
                    'source_layer': src_layer,
                    'target': dst,
                    'target_layer': dst_layer,
                    'reason': f'Lower architectural layer ({src_layer}) depends on presentation layer ({dst_layer}).',
                })

    return {
        'layers': {layer: {'count': len(files), 'files': files[:25]} for layer, files in sorted(layer_files.items())},
        'coupling_metrics': sorted(module_metrics, key=lambda m: -(m['afferent_coupling_ca'] + m['efferent_coupling_ce']))[:60],
        'inferred_layer_violations': inferred_layer_violations,
    }


def check_doc_consistency(
    sources: dict[str, str],
    parsed_files: dict[str, dict],
) -> dict[str, Any]:
    """Compare Markdown documentation references against actual indexed files, symbols, and RPC routes."""
    known_paths = set(sources.keys()) | set(parsed_files.keys())
    known_basenames = {PurePosixPath(p).name for p in known_paths}
    known_symbols = {
        s.get('name')
        for item in parsed_files.values()
        for s in item.get('symbols', [])
        if s.get('name')
    }
    known_contracts = {
        c.get('endpoint')
        for item in parsed_files.values()
        for c in item.get('contracts', [])
        if c.get('endpoint')
    }

    md_files = [p for p in sorted(sources) if p.lower().endswith(('.md', '.mdx'))]
    stale_file_refs = []
    verified_refs = 0

    path_pattern = re.compile(r'`((?:src|backend|docs|scripts|src-tauri)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`')
    for md_path in md_files:
        text = sources.get(md_path, '')
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in path_pattern.finditer(line):
                ref_path = match.group(1).strip()
                if '*' in ref_path or '...' in ref_path:
                    continue
                if ref_path in known_paths or PurePosixPath(ref_path).name in known_basenames:
                    verified_refs += 1
                else:
                    stale_file_refs.append({
                        'doc_path': md_path,
                        'line': lineno,
                        'referenced_path': ref_path,
                        'reason': 'Referenced file path in documentation does not exist in workspace.',
                    })

    stale_doc_params = []
    for path, item in sorted(parsed_files.items()):
        for sym in item.get('symbols', []):
            doc_params = [p.get('name') for p in (sym.get('doc_params') or []) if p.get('name')]
            if not doc_params:
                continue
            actual_params = {p.get('name') if isinstance(p, dict) else str(p) for p in (sym.get('parameters') or [])}
            extra = [dp for dp in doc_params if dp not in actual_params]
            if extra:
                stale_doc_params.append({
                    'path': path,
                    'symbol': sym.get('qualified_name') or sym.get('name'),
                    'line': sym.get('line', 1),
                    'stale_doc_params': extra,
                })

    return {
        'markdown_files_checked': len(md_files),
        'verified_code_references': verified_refs,
        'known_contract_endpoints': sorted(known_contracts)[:40],
        'known_symbol_count': len(known_symbols),
        'stale_references': stale_file_refs[:30],
        'stale_docstring_params': stale_doc_params[:30],
        'status': 'consistent' if not (stale_file_refs or stale_doc_params) else 'drift_detected',
    }


def resolve_call_graph_and_contracts(parsed_files: dict[str, dict]) -> dict[str, Any]:
    """Build cross-file symbol call resolution and cross-language RPC/HTTP/IPC contract links."""
    symbol_defs: dict[str, list[dict]] = defaultdict(list)
    for path, item in sorted(parsed_files.items()):
        for sym in item.get('symbols', []):
            name = sym.get('name')
            if name:
                symbol_defs[name].append({
                    'path': path,
                    'qualified_name': sym.get('qualified_name') or name,
                    'kind': sym.get('kind'),
                    'line': sym.get('line', 1),
                    'exported': sym.get('exported', True),
                })

    callers_by_symbol: dict[str, list[dict]] = defaultdict(list)
    for path, item in sorted(parsed_files.items()):
        for sym in item.get('symbols', []):
            caller_name = sym.get('qualified_name') or sym.get('name')
            caller_line = sym.get('line', 1)
            for callee in sym.get('calls', []):
                short_callee = callee.split('.')[-1].split('::')[-1]
                if short_callee in symbol_defs:
                    callers_by_symbol[short_callee].append({
                        'caller_path': path,
                        'caller_symbol': caller_name,
                        'caller_line': caller_line,
                        'callee': callee,
                    })

    # Match cross-language contracts (e.g. TS rpc/invoke <-> Python/Rust handler)
    handlers: dict[str, list[dict]] = defaultdict(list)
    clients: dict[str, list[dict]] = defaultdict(list)
    for path, item in sorted(parsed_files.items()):
        for contract in item.get('contracts', []):
            ep = contract.get('endpoint', '')
            kind = contract.get('kind', '')
            entry = {'path': path, 'line': contract.get('line', 1), 'kind': kind, 'endpoint': ep}
            if 'handler' in kind or 'command' in kind:
                handlers[ep].append(entry)
            else:
                clients[ep].append(entry)

    linked_contracts = []
    unmatched_client_calls = []
    for ep, client_list in sorted(clients.items()):
        matched_handlers = handlers.get(ep, [])
        if matched_handlers:
            linked_contracts.append({
                'endpoint': ep,
                'clients': client_list[:8],
                'handlers': matched_handlers[:8],
            })
        else:
            unmatched_client_calls.append({
                'endpoint': ep,
                'clients': client_list[:5],
            })

    return {
        'symbol_defs': symbol_defs,
        'callers_by_symbol': callers_by_symbol,
        'linked_contracts': linked_contracts,
        'unmatched_client_calls': unmatched_client_calls,
    }


def compare_revisions(
    base_files: dict[str, dict],
    candidate_files: dict[str, dict],
) -> dict[str, Any]:
    """Compare base vs candidate parsed file graphs to detect added/removed/modified symbols and signature changes."""
    added_files = sorted(set(candidate_files) - set(base_files))
    removed_files = sorted(set(base_files) - set(candidate_files))
    common_files = sorted(set(base_files) & set(candidate_files))

    added_symbols = []
    removed_symbols = []
    signature_changes = []
    modified_symbols = []

    for path in common_files:
        b_item = base_files[path]
        c_item = candidate_files[path]
        if b_item.get('sha256') == c_item.get('sha256'):
            continue
        b_syms = {(s.get('qualified_name') or s.get('name')): s for s in b_item.get('symbols', [])}
        c_syms = {(s.get('qualified_name') or s.get('name')): s for s in c_item.get('symbols', [])}
        for name in sorted(set(c_syms) - set(b_syms)):
            added_symbols.append({'path': path, 'symbol': name, 'kind': c_syms[name].get('kind'), 'line': c_syms[name].get('line', 1)})
        for name in sorted(set(b_syms) - set(c_syms)):
            removed_symbols.append({'path': path, 'symbol': name, 'kind': b_syms[name].get('kind'), 'line': b_syms[name].get('line', 1), 'exported': b_syms[name].get('exported', True)})
        for name in sorted(set(b_syms) & set(c_syms)):
            bs, cs = b_syms[name], c_syms[name]
            if bs.get('signature') != cs.get('signature') or bs.get('return_type') != cs.get('return_type'):
                signature_changes.append({
                    'path': path,
                    'symbol': name,
                    'before_signature': bs.get('signature'),
                    'after_signature': cs.get('signature'),
                    'exported': cs.get('exported', True),
                    'breaking': bool(cs.get('exported', True)),
                })
            elif bs.get('calls') != cs.get('calls') or bs.get('complexity') != cs.get('complexity'):
                modified_symbols.append({
                    'path': path,
                    'symbol': name,
                    'line': cs.get('line', 1),
                })

    return {
        'added_files': added_files,
        'removed_files': removed_files,
        'added_symbols': added_symbols,
        'removed_symbols': removed_symbols,
        'signature_changes': signature_changes,
        'modified_symbols': modified_symbols,
        'breaking_symbol_changes': [s for s in signature_changes if s.get('breaking')] + [s for s in removed_symbols if s.get('exported')],
    }


def validate_schema_changes(parsed_files: dict[str, dict], target_paths: list[str] | None = None) -> dict[str, Any]:
    """Inspect SQL statements and DDL migrations across files using sqlglot AST extraction."""
    tables = set()
    ddl_statements = []
    destructive_operations = []
    errors = []

    for path, item in sorted(parsed_files.items()):
        if target_paths and path not in target_paths:
            continue
        sql_info = item.get('sql') or {}
        for t in sql_info.get('tables', []):
            tables.add(t)
        for d in sql_info.get('ddl', []):
            entry = {'path': path, **d}
            ddl_statements.append(entry)
            op = (d.get('op') or d.get('kind') or '').lower()
            actions_text = ' '.join(d.get('actions') or []).upper()
            stmt_upper = (d.get('statement') or '').upper()
            if 'drop' in op or 'DROP COLUMN' in actions_text or 'DROP' in stmt_upper:
                destructive_operations.append({
                    'path': path,
                    'line': d.get('line', 1),
                    'kind': d.get('op') or d.get('kind'),
                    'table': d.get('table'),
                    'reason': 'Destructive SQL schema operation (DROP TABLE / DROP COLUMN) may break existing queries.',
                })
        for err in sql_info.get('errors', []):
            errors.append({'path': path, **err})

    return {
        'tables': sorted(tables),
        'ddl_operations': ddl_statements[:50],
        'destructive_operations': destructive_operations,
        'sql_syntax_errors': errors,
        'compatible': len(destructive_operations) == 0 and len(errors) == 0,
    }


def correlate_error(
    error_text: str,
    parsed_files: dict[str, dict],
    inbound: dict[str, set[str]],
    outbound: dict[str, set[str]],
) -> dict[str, Any]:
    """Parse stack traces or error messages (Python, TS/JS, Rust, Go) and map frames to indexed symbols and callers."""
    frames = []
    known_paths = sorted(parsed_files.keys())

    def match_workspace_path(raw_path: str) -> str | None:
        clean = raw_path.strip().replace('\\', '/').lstrip('./')
        if clean in parsed_files:
            return clean
        for kp in known_paths:
            if clean.endswith('/' + kp) or clean.endswith(kp) or kp.endswith(clean):
                return kp
        return None

    # Python: File "path.py", line 42, in func_name
    for m in re.finditer(r'File "([^"]+)", line (\d+)(?:, in ([A-Za-z0-9_<>.]+))?', error_text):
        raw_p, line_s, func = m.group(1), m.group(2), m.group(3)
        frames.append({'raw_path': raw_p, 'line': int(line_s), 'function': func, 'runtime': 'python'})

    # JS/TS/Rust/Go: at func (path:line:col) or path:line:col
    for m in re.finditer(r'(?:at\s+([A-Za-z0-9_$.<>]+)\s+\()?([A-Za-z0-9_./\\-]+\.(?:ts|tsx|js|jsx|py|rs|go|c|cpp|java)):(\d+)(?::(\d+))?\)?', error_text):
        func, raw_p, line_s = m.group(1), m.group(2), m.group(3)
        frames.append({'raw_path': raw_p, 'line': int(line_s), 'function': func, 'runtime': 'generic'})

    resolved_frames = []
    seen = set()
    for frame in frames:
        ws_path = match_workspace_path(frame['raw_path'])
        line = frame['line']
        key = (ws_path or frame['raw_path'], line)
        if key in seen:
            continue
        seen.add(key)
        enclosing_sym = None
        if ws_path and ws_path in parsed_files:
            for sym in parsed_files[ws_path].get('symbols', []):
                s_start = int(sym.get('line', 1))
                s_end = int(sym.get('end_line', s_start))
                if s_start <= line <= s_end:
                    enclosing_sym = sym
                    break
        resolved_frames.append({
            'workspace_path': ws_path,
            'raw_path': frame['raw_path'],
            'line': line,
            'function': (enclosing_sym.get('qualified_name') if enclosing_sym else frame.get('function')),
            'signature': enclosing_sym.get('signature') if enclosing_sym else None,
            'side_effects': enclosing_sym.get('side_effects', []) if enclosing_sym else [],
            'calls': enclosing_sym.get('calls', [])[:10] if enclosing_sym else [],
            'inbound_files': sorted(inbound.get(ws_path, set()))[:8] if ws_path else [],
            'outbound_files': sorted(outbound.get(ws_path, set()))[:8] if ws_path else [],
        })

    root_cause_frame = next((f for f in reversed(resolved_frames) if f.get('workspace_path')), resolved_frames[-1] if resolved_frames else None)
    return {
        'frame_count': len(resolved_frames),
        'frames': resolved_frames,
        'root_cause_candidate': root_cause_frame,
    }


def build_refactor_plan(
    paths: list[str],
    symbol: str | None,
    goal: str | None,
    parsed_files: dict[str, dict],
    impact_report: dict[str, Any],
) -> dict[str, Any]:
    """Generate a structured multi-file refactoring plan with dependency order, contract checks, and verification steps."""
    steps = []
    step_no = 1
    target_files = [p for p in paths if p in parsed_files] or list(paths)

    if symbol:
        callers = impact_report.get('symbol_callers', [])
        steps.append({
            'step': step_no,
            'phase': 'interface_preparation',
            'targets': target_files,
            'description': f'Update symbol `{symbol}` definition and preserve backward-compatible signature where possible.',
            'affected_callers_count': len(callers),
        })
        step_no += 1
        if callers:
            caller_paths = sorted({c['caller_path'] for c in callers if c.get('caller_path')})
            steps.append({
                'step': step_no,
                'phase': 'caller_migration',
                'targets': caller_paths,
                'description': f'Update {len(callers)} call sites across {len(caller_paths)} files referencing `{symbol}`.',
                'call_sites': callers[:15],
            })
            step_no += 1
    else:
        steps.append({
            'step': step_no,
            'phase': 'module_modification',
            'targets': target_files,
            'description': goal or f'Apply planned refactoring across {", ".join(target_files[:5])}.',
        })
        step_no += 1

    direct = impact_report.get('direct_dependents', [])
    if direct:
        steps.append({
            'step': step_no,
            'phase': 'dependent_propagation',
            'targets': direct[:15],
            'description': f'Verify and update {len(direct)} directly importing modules.',
        })
        step_no += 1

    contracts = impact_report.get('affected_contracts', [])
    if contracts:
        steps.append({
            'step': step_no,
            'phase': 'contract_synchronization',
            'targets': sorted({c['path'] for c in contracts if c.get('path')}),
            'description': 'Synchronize RPC/IPC/HTTP request and response schemas across frontend and backend boundaries.',
            'contracts': contracts[:10],
        })
        step_no += 1

    tests = impact_report.get('affected_tests', [])
    steps.append({
        'step': step_no,
        'phase': 'verification',
        'targets': tests[:15],
        'description': f'Run {len(tests)} affected test modules and static quality/security gates.' if tests else 'Run project test suite and static analysis gates.',
    })

    return {
        'goal': goal or (f'Refactor {symbol}' if symbol else 'Multi-file refactoring'),
        'target_paths': target_files,
        'symbol': symbol,
        'risk': impact_report.get('risk', {}),
        'steps': steps,
        'affected_tests': tests,
    }


def discover_external_connectors(root: Path, sources: dict[str, str]) -> dict[str, Any]:
    """Discover MCP servers, ADRs, issue templates, and external context connectors in the workspace."""
    mcp_servers = []
    adr_docs = []
    ci_workflows = []

    for path, text in sorted(sources.items()):
        name = PurePosixPath(path).name.lower()
        if name in {'mcp.json', '.mcp.json', 'claude_desktop_config.json'}:
            try:
                doc = json.loads(text)
                servers = doc.get('mcpServers') or doc.get('servers') or {}
                for srv_name, cfg in servers.items():
                    mcp_servers.append({
                        'name': srv_name,
                        'path': path,
                        'command': cfg.get('command') if isinstance(cfg, dict) else None,
                        'transport': cfg.get('transport', 'stdio') if isinstance(cfg, dict) else 'stdio',
                    })
            except Exception:
                pass
        elif ('docs/architecture/' in path or 'adr' in path.lower()) and path.endswith('.md'):
            title = next((line.lstrip('# ').strip() for line in text.splitlines() if line.startswith('#')), PurePosixPath(path).stem)
            adr_docs.append({'path': path, 'title': title})
        elif path.startswith('.github/workflows/') and path.endswith(('.yml', '.yaml')):
            ci_workflows.append({'path': path, 'name': PurePosixPath(path).stem})

    return {
        'mcp_servers': mcp_servers,
        'architecture_docs': adr_docs[:30],
        'ci_workflows': ci_workflows[:20],
        'builtin_mcp_endpoint': 'shark-code-mcp',
    }
