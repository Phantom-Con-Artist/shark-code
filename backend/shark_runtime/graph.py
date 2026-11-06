"""Versioned Graphify index, bounded retrieval and evidence-backed impact paths."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
import threading
from collections import defaultdict, deque
from pathlib import Path

from .core import Core, Fault, confined, write_json

CODE = {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs", ".go", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".kt", ".swift", ".scala"}
WEB_ASSETS = {".html", ".htm", ".css", ".ipynb"}
CONFIG = {"package.json", "tsconfig.json", "jsconfig.json", "Cargo.toml", "go.mod", "pyproject.toml"}
# Structural containment is useful for navigation, but must never turn a single
# changed symbol into an assertion that every symbol in its file is affected.
DEPENDENCIES = {"calls", "indirect_call", "imports", "imports_from", "uses", "references", "inherits", "implements", "mixes_in", "re_exports"}
MAX_GRAPH_BYTES = 64 * 1024 * 1024


def bounded(value: dict, budget: int = 24000) -> dict:
    """Drop whole rows with explicit truncation, retaining valid JSON and evidence."""
    while len(json.dumps(value, ensure_ascii=False).encode()) > budget:
        if isinstance(value.get("graph"), dict):
            value["graph"] = bounded(value["graph"], budget - 2000)
            value["truncated"] = True
            continue
        for key in ("edges", "nodes", "affected", "seeds", "files", "skipped"):
            if isinstance(value.get(key), list) and value[key]:
                value[key].pop()
                value["truncated"] = True
                break
        else:
            raise Fault("result_too_large", "Narrow the query to return bounded evidence")
    return value


class Graph:
    def __init__(self, core: Core):
        self.core = core
        self.directory = core.root / ".shark" / "graph"
        self.directory.mkdir(exist_ok=True)
        if self.directory.is_symlink():
            raise Fault("invalid_state", "Graph storage must be a real directory")
        self.path = self.directory / "index.json"
        self.lock = threading.RLock()
        self.version = importlib.metadata.version("graphifyy")
        self._graph = None

    def snapshot(self) -> dict:
        snapshot = self.core.call("workspace/snapshot")
        selected = [f for f in snapshot["files"] if Path(f["path"]).suffix in (CODE | WEB_ASSETS) or Path(f["path"]).name in CONFIG]
        if len(selected) > 5000:
            raise Fault("graph_too_large", "Choose a workspace with at most 5,000 graph input files")
        signature = json.dumps(["shark-graph-v2-notebooks", self.version, selected, snapshot["skipped"]], sort_keys=True).encode()
        return {"revision": hashlib.sha256(signature).hexdigest(), "files": selected,
                "skipped": snapshot["skipped"], "unindexed_files": len(snapshot["files"]) - len(selected)}

    def ensure(self, force=False) -> dict:
        with self.lock:
            snapshot = self.snapshot()
            if self._graph is None and self.path.exists():
                try:
                    if self.path.stat().st_size <= MAX_GRAPH_BYTES:
                        saved = json.loads(self.path.read_text())
                        if saved.get("schema_version") == 1 and saved.get("provider_version") == self.version:
                            self._graph = saved
                except (OSError, ValueError):
                    pass
            if not force and self._graph and self._graph["revision"] == snapshot["revision"]:
                return self._graph
            with tempfile.TemporaryDirectory(prefix="input-", dir=self.directory) as folder:
                root = Path(folder)
                for f in snapshot["files"]:
                    target = confined(root, f["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Inputs are immutable, content-addressed artifacts created by
                    # the native boundary, not arbitrary files from the live tree.
                    artifact = self.core.root / ".shark" / "artifacts" / f["artifact_id"]
                    target.write_bytes(artifact.read_bytes())
                worker_files = [f["path"] for f in snapshot["files"] if Path(f["path"]).suffix in CODE or Path(f["path"]).name in CONFIG]
                request = {"root": str(root), "files": worker_files, "cache": str(self.directory)}
                with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as diagnostics:
                    try:
                        process = subprocess.run([sys.executable, "--graph-worker"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "shark_runtime.graph_worker"],
                            input=json.dumps(request).encode(), stdout=output, stderr=diagnostics, timeout=120)
                    except subprocess.TimeoutExpired as exc:
                        raise Fault("index_timeout", "Graphify exceeded the 120-second indexing limit") from exc
                    if process.returncode:
                        raise Fault("index_failed", "Graphify extraction failed; the previous graph was retained")
                    if output.tell() > MAX_GRAPH_BYTES:
                        raise Fault("graph_too_large", "Graphify output exceeded 64 MiB")
                    output.seek(0)
                    raw = json.load(output)
                failed = raw.get("failed_sources", [])
                if failed:
                    raise Fault("index_incomplete", f"Graphify failed on {len(failed)} input files; previous graph retained")
                if self.snapshot()["revision"] != snapshot["revision"]:
                    raise Fault("workspace_changed", "Workspace changed while indexing; retry on current source")
                graph = self.normalize(raw, snapshot, root)
            write_json(self.path, graph)
            self._graph = graph
            return graph

    def normalize(self, raw, snapshot, root):
        manifest = {f["path"]: f for f in snapshot["files"]}
        nodes = []
        for row in raw.get("nodes", []):
            source = str(row.get("source_file") or "")
            if Path(source).is_absolute():
                try:
                    source = Path(source).relative_to(root).as_posix()
                except ValueError:
                    source = ""
            entry = manifest.get(source)
            nodes.append({"id": str(row["id"]), "label": str(row.get("label", row["id"]))[:400],
                "kind": str(row.get("type", row.get("file_type", "symbol")))[:100],
                "path": source if entry else None, "location": str(row.get("source_location") or "")[:100],
                "version": entry["version"] if entry else None,
                "artifact_id": entry["artifact_id"] if entry else None,
                "external": entry is None})
        ids = {n["id"] for n in nodes}
        edges = []
        unresolved = 0
        for row in raw.get("edges", []):
            src, dst = str(row.get("source", "")), str(row.get("target", ""))
            if src not in ids or dst not in ids:
                unresolved += 1
                continue
            confidence = row.get("confidence", "UNKNOWN")
            edges.append({"source": src, "target": dst, "relation": str(row.get("relation", "related"))[:100],
                "confidence": confidence if confidence in ("EXTRACTED", "INFERRED") else "UNKNOWN",
                "evidence": str(row.get("context") or row.get("description") or row.get("relation", ""))[:600]})
        # Merge HTML resource links and alias-resolved module edges from Codebase Intelligence
        try:
            from .codebase import dependencies as cb_deps, engine as cb_engine, syntax as cb_syntax
            sources = {}
            for p in manifest:
                try:
                    sources[p] = (root / p).read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    pass
            aliases = cb_deps.inventory(sources).get("aliases", [])
            file_node_by_path = {}
            for n in nodes:
                if n.get("path") and n["path"] not in file_node_by_path:
                    file_node_by_path[n["path"]] = n["id"]
            for p, entry in manifest.items():
                if p not in file_node_by_path:
                    nid = f"file:{p}"
                    nodes.append({
                        "id": nid, "label": Path(p).name[:400], "kind": "module",
                        "path": p, "location": f"{p}:1", "version": entry["version"],
                        "artifact_id": entry["artifact_id"], "external": False,
                    })
                    ids.add(nid)
                    file_node_by_path[p] = nid
            existing_pairs = {(e["source"], e["target"], e["relation"]) for e in edges}
            all_paths = set(manifest)
            for p, text in sources.items():
                parsed = cb_syntax.parse(p, text)
                src_id = file_node_by_path.get(p)
                if not src_id:
                    continue
                if p.lower().endswith('.ipynb'):
                    for symbol in parsed.get('symbols', []):
                        nid = 'notebook:' + symbol['id']
                        nodes.append({'id': nid, 'label': symbol['qualified_name'], 'kind': symbol['kind'], 'path': p,
                                      'location': f"cell {symbol.get('cell_index', 0) + 1}:L{symbol.get('cell_line', 1)}",
                                      'cell_id': symbol.get('cell_id'), 'cell_line': symbol.get('cell_line'),
                                      'version': manifest[p]['version'], 'artifact_id': manifest[p]['artifact_id'], 'external': False})
                        ids.add(nid)
                        edges.append({'source': src_id, 'target': nid, 'relation': 'contains', 'confidence': 'EXTRACTED', 'evidence': p})
                for imp in parsed.get("imports", []):
                    resolved_target = cb_engine.resolve_import(p, imp, all_paths, aliases)
                    dst_id = file_node_by_path.get(resolved_target) if resolved_target else None
                    if dst_id and (src_id, dst_id, "imports") not in existing_pairs:
                        existing_pairs.add((src_id, dst_id, "imports"))
                        edges.append({
                            "source": src_id, "target": dst_id, "relation": "imports",
                            "confidence": "EXTRACTED",
                            "evidence": f"{p}:{imp.get('line', 1)} imports {imp.get('source', '')}"[:600],
                        })
        except Exception:
            pass
        if len(nodes) > 100000 or len(edges) > 300000:
            raise Fault("graph_too_large", "Graph exceeds 100,000 nodes or 300,000 edges")
        return {"schema_version": 1, "provider": "graphify", "provider_version": self.version,
            "revision": snapshot["revision"], "manifest": snapshot["files"], "nodes": nodes, "edges": edges,
            "coverage": {"input_files": len(manifest), "unindexed_files": snapshot["unindexed_files"],
                "skipped": snapshot["skipped"][:50], "skipped_count": len(snapshot["skipped"]), "unresolved_edges": unresolved,
                "declined_files": len(raw.get("skipped_sources", [])),
                "semantic_completeness": False}}

    @staticmethod
    def summary(graph):
        return bounded({k: graph[k] for k in ("provider", "provider_version", "revision", "coverage")} | {
            "node_count": len(graph["nodes"]), "edge_count": len(graph["edges"]), "truncated": False})

    @staticmethod
    def select(graph, query, limit):
        if not isinstance(query, str) or len(query) > 500 or not query.strip():
            raise Fault("invalid_query", "Supply a symbol, relative file path, or a short question")
        terms = set(re.findall(r"[\w]+", query.lower())) - {"the", "a", "an", "how", "what", "does", "where", "is", "of", "to"}
        scored = []
        for node in graph["nodes"]:
            label, path = node["label"].lower(), (node["path"] or "").lower()
            haystack = label + " " + path
            exact = query.lower() in (node["id"].lower(), label, path)
            score = 100 if exact else sum(1 for term in terms if term in haystack)
            if score:
                scored.append((-score, node["external"], node["id"], node))
        return [x[3] for x in sorted(scored, key=lambda x: x[:3])[:limit]]

    def query(self, query, limit=20):
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise Fault("invalid_limit", "Graph query limit must be 1–50")
        graph = self.ensure()
        seeds = self.select(graph, query, limit + 1)
        truncated = len(seeds) > limit
        seeds = seeds[:limit]
        ids = {n["id"] for n in seeds}
        links = [e for e in graph["edges"] if e["source"] in ids or e["target"] in ids]
        relevant = set(ids)
        for e in links[:100]:
            relevant.update((e["source"], e["target"]))
        nodes = seeds + [n for n in graph["nodes"] if n["id"] in relevant - ids][:80]
        return bounded({"revision": graph["revision"], "provider": "graphify", "seeds": seeds,
            "nodes": nodes, "edges": links[:100], "coverage": graph["coverage"],
            "truncated": truncated or len(links) > 100})

    def impact(self, paths=None, node_id=None, depth=3, limit=50):
        if not isinstance(depth, int) or not 1 <= depth <= 6 or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise Fault("invalid_range", "Impact depth must be 1–6 and limit 1–100")
        graph = self.ensure()
        by_id = {n["id"]: n for n in graph["nodes"]}
        if node_id is not None:
            if node_id not in by_id:
                raise Fault("unknown_node", "Use an exact node ID returned by graph/query")
            seeds = {node_id}
        else:
            if not isinstance(paths, list) or not 1 <= len(paths) <= 50:
                raise Fault("invalid_paths", "Impact needs 1–50 changed file paths")
            for path in paths:
                confined(self.core.root, path)
            seeds = {n["id"] for n in graph["nodes"] if n["path"] in paths}
        incoming = defaultdict(list)
        for edge in graph["edges"]:
            if edge["relation"] in DEPENDENCIES:
                incoming[edge["target"]].append(edge)
        seen = set(seeds)
        queue = deque((s, []) for s in sorted(seeds))
        affected = []
        truncated = False
        while queue:
            target, evidence = queue.popleft()
            if len(evidence) >= depth:
                truncated |= any(e["source"] not in seen for e in incoming[target])
                continue
            for edge in incoming[target]:
                caller = edge["source"]
                if caller in seen:
                    continue
                if len(affected) >= limit:
                    truncated = True
                    queue.clear()
                    break
                seen.add(caller)
                chain = [edge] + evidence
                affected.append({"node": by_id[caller], "distance": len(chain), "evidence_path": chain,
                    "confidence": "EXTRACTED" if all(e["confidence"] == "EXTRACTED" for e in chain) else "INFERRED"})
                queue.append((caller, chain))
        return bounded({"revision": graph["revision"], "changed_paths": paths or [], "seed_count": len(seeds),
            "affected": affected, "coverage": graph["coverage"], "truncated": truncated,
            "analysis": "Static reverse dependency reachability; not proof of runtime effects or test coverage."})
