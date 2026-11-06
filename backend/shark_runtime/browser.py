"""Shark's built-in browser: a local preview server with element picking, plus headless page checks.

`serve(root, target)` starts (once per target) a 127.0.0.1 server that either serves the project's
static files (target "workspace") or reverse-proxies a local dev server (target "http://localhost:5173").
Every HTML response gets a small picker script. In pick mode a click posts the element's selector,
text and markup to the Shark window, which asks `locate()` for the source lines that most likely
render it. Console errors are forwarded the same way.

`check(url)` drives headless Chromium through Playwright (when installed) and reports console
errors, failed requests, the page title and a screenshot, for both the user and agents.
"""
from __future__ import annotations

import html
import http.server
import mimetypes
import re
import socketserver
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .cli_agents import which

PICKER = r"""<script data-shark-picker>(() => {
  if (window.__sharkPicker) return; window.__sharkPicker = true;
  let picking = false, box = null;
  const post = (m) => { try { parent.postMessage(Object.assign({ source: 'shark-browser' }, m), '*'); } catch {} };
  const css = (el) => { if (!(el instanceof Element)) return '';
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = []; let n = el;
    while (n && n.nodeType === 1 && parts.length < 5) {
      let p = n.tagName.toLowerCase();
      const cls = [...n.classList].filter(c => !c.startsWith('__shark')).slice(0, 2);
      if (cls.length) p += '.' + cls.map(c => CSS.escape(c)).join('.');
      const sib = n.parentElement ? [...n.parentElement.children].filter(c => c.tagName === n.tagName) : [];
      if (sib.length > 1 && !cls.length) p += ':nth-of-type(' + (sib.indexOf(n) + 1) + ')';
      parts.unshift(p); if (n.id) break; n = n.parentElement;
    }
    return parts.join(' > ');
  };
  const outline = (el) => { if (!box) { box = document.createElement('div'); box.className = '__shark-box';
      box.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483647;border:1.5px solid #12a594;background:rgba(18,165,148,.08);border-radius:3px;transition:all .08s ease-out';
      document.documentElement.appendChild(box); }
    const r = el.getBoundingClientRect(); Object.assign(box.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px', display: 'block' }); };
  const over = (e) => { if (picking && e.target !== box) outline(e.target); };
  const click = (e) => { if (!picking) return; e.preventDefault(); e.stopPropagation();
    const el = e.target, r = el.getBoundingClientRect();
    post({ type: 'pick', url: location.href, selector: css(el), tag: el.tagName.toLowerCase(), id: el.id || '',
      classes: [...el.classList], text: (el.innerText || el.textContent || '').trim().slice(0, 200),
      html: el.outerHTML.slice(0, 1200), rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } });
    set(false); };
  const set = (on) => { picking = on; document.documentElement.style.cursor = on ? 'crosshair' : ''; if (!on && box) box.style.display = 'none'; post({ type: 'picking', on }); };
  addEventListener('mouseover', over, true); addEventListener('click', click, true);
  addEventListener('keydown', (e) => { if (e.key === 'Escape' && picking) set(false); }, true);
  addEventListener('message', (e) => { const d = e.data || {}; if (d.source === 'shark' && d.type === 'pick-mode') set(!!d.on); });
  const fwd = (level, args) => post({ type: 'console', level, message: args.map(a => { try { return a instanceof Error ? a.stack || a.message : typeof a === 'object' ? JSON.stringify(a) : String(a); } catch { return String(a); } }).join(' ').slice(0, 2000) });
  for (const level of ['error', 'warn']) { const orig = console[level]; console[level] = (...a) => { fwd(level, a); orig.apply(console, a); }; }
  addEventListener('error', (e) => fwd('error', [e.error || e.message + ' (' + e.filename + ':' + e.lineno + ')']));
  addEventListener('unhandledrejection', (e) => fwd('error', ['Unhandled rejection: ', e.reason]));
  post({ type: 'loaded', url: location.href, title: document.title });
})();</script>"""

HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "content-encoding", "proxy-connection", "upgrade",
       "content-security-policy", "x-frame-options"}
SERVERS: dict[tuple[str, str], tuple[socketserver.TCPServer, str]] = {}
LOCK = threading.Lock()


def inject(body: bytes) -> bytes:
    text = body.decode("utf-8", errors="replace")
    match = re.search(r"</head\s*>", text, re.I) or re.search(r"<body[^>]*>", text, re.I)
    if match:
        at = match.start() if match.group(0).lower().startswith("</head") else match.end()
        return (text[:at] + PICKER + text[at:]).encode("utf-8")
    return (PICKER + text).encode("utf-8")


def _handler(root: Path, target: str):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, status, headers, body):
            self.send_response(status)
            for k, v in headers:
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _static(self):
            rel = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/")
            path = (root / rel).resolve()
            if not path.is_relative_to(root.resolve()):
                return self._send(403, [], b"Forbidden")
            if path.is_dir():
                path = path / "index.html"
            if not path.is_file():
                listing = "".join(f'<li><a href="/{html.escape(p.relative_to(root).as_posix())}">{html.escape(p.relative_to(root).as_posix())}</a></li>'
                                  for p in sorted(root.rglob("*.html"))[:200] if ".git" not in p.parts and "node_modules" not in p.parts)
                body = f"<!doctype html><title>Not found</title><h1>Not found</h1><p>{html.escape(rel)}</p><ul>{listing}</ul>".encode()
                return self._send(404, [("Content-Type", "text/html; charset=utf-8")], inject(body))
            body = path.read_bytes()
            kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if kind == "text/html":
                body = inject(body)
            self._send(200, [("Content-Type", kind + ("; charset=utf-8" if kind.startswith("text/") else ""))], body)

        def _proxy(self):
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP | {"host", "accept-encoding"}}
            request = urllib.request.Request(target.rstrip("/") + self.path, data=data, headers=headers, method=self.command)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    status, out, body = response.status, response.getheaders(), response.read()
            except urllib.error.HTTPError as err:
                status, out, body = err.code, err.headers.items(), err.read()
            except Exception as exc:
                body = f"<!doctype html><title>Unreachable</title><p>Shark could not reach {html.escape(target)}: {html.escape(str(exc))}</p>".encode()
                return self._send(502, [("Content-Type", "text/html; charset=utf-8")], inject(body))
            if any(k.lower() == "content-type" and "text/html" in v for k, v in out):
                body = inject(body)
            self._send(status, out, body)

        def _handle(self):
            try:
                self._static() if target == "workspace" else self._proxy()
            except (BrokenPipeError, ConnectionResetError):
                pass

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

    return Handler


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(root: Path, target: str = "workspace") -> dict:
    target = (target or "workspace").strip()
    if target != "workspace":
        parts = urllib.parse.urlsplit(target if "://" in target else "http://" + target)
        if parts.scheme not in ("http", "https") or parts.hostname not in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            raise ValueError("Shark's browser previews local servers only (localhost or 127.0.0.1)")
        target = f"{parts.scheme}://{parts.netloc}"
        path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
    else:
        path = "/"
    key = (str(root), target)
    with LOCK:
        if key not in SERVERS:
            server = _Server(("127.0.0.1", 0), _handler(Path(root), target))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            SERVERS[key] = (server, f"http://127.0.0.1:{server.server_address[1]}")
        base = SERVERS[key][1]
    return {"url": base + path, "base": base, "target": target}


def close(root: Path | None = None):
    with LOCK:
        for key, (server, _) in list(SERVERS.items()):
            if root is None or key[0] == str(root):
                server.shutdown()
                server.server_close()
                SERVERS.pop(key, None)


SOURCE_EXT = {".html", ".htm", ".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte", ".astro", ".css", ".scss", ".md", ".mdx", ".php", ".erb", ".hbs"}


def locate(root: Path, pick: dict, limit: int = 8) -> dict:
    """Rank the source lines that most likely render a picked element: id, classes, then visible text."""
    needles: list[tuple[str, int]] = []
    if pick.get("id"):
        needles.append((pick["id"], 5))
    for c in (pick.get("classes") or [])[:4]:
        if isinstance(c, str) and len(c) > 2:
            needles.append((c, 2))
    text = re.sub(r"\s+", " ", str(pick.get("text") or "")).strip()
    for chunk in [text[:60]] + re.split(r"[.!?\n]", text)[:2]:
        chunk = chunk.strip()
        if len(chunk) >= 6:
            needles.append((chunk[:60], 4))
    scores: dict[tuple[str, int], list] = {}
    rg = which("rg")
    for needle, weight in needles:
        hits = []
        if rg:
            out = subprocess.run([rg, "--no-heading", "-n", "-F", "--max-count", "5", "-g", "!node_modules", "-g", "!dist",
                                  "-g", "!build", "-g", "!.shark", "--", needle, str(root)], capture_output=True, text=True, timeout=10)
            for line in out.stdout.splitlines()[:40]:
                file, _, rest = line.partition(":")
                num, _, snippet = rest.partition(":")
                if num.isdigit():
                    hits.append((file, int(num), snippet))
        else:
            for p in root.rglob("*"):
                if p.suffix in SOURCE_EXT and p.is_file() and not {"node_modules", ".git", "dist"} & set(p.parts):
                    for i, l in enumerate(p.read_text(errors="replace").splitlines(), 1):
                        if needle in l:
                            hits.append((str(p), i, l))
        for file, num, snippet in hits:
            path = Path(file)
            if path.suffix not in SOURCE_EXT:
                continue
            key = (path.resolve().relative_to(root.resolve()).as_posix(), num)
            entry = scores.setdefault(key, [0, snippet.strip()[:200], set()])
            entry[0] += weight + (1 if path.suffix in {".html", ".jsx", ".tsx", ".vue", ".svelte", ".astro"} else 0)
            entry[2].add(needle)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1][0], kv[0]))[:limit]
    return {"matches": [{"path": p, "line": n, "snippet": s, "score": sc, "matched": sorted(m)} for (p, n), (sc, s, m) in ranked]}


def check(url: str, timeout_ms: int = 15000) -> dict:
    """Headless page check through Playwright: console errors, failed requests, title and a screenshot."""
    from .core import Fault
    try:
        parts = urllib.parse.urlsplit(url)
        allowed = (parts.scheme in {"http", "https"} and parts.hostname in {"localhost", "127.0.0.1", "::1"}
                   and not parts.username and not parts.password)
    except (TypeError, ValueError):
        allowed = False
    if not allowed:
        raise Fault("invalid_params", "Page checks require a localhost HTTP(S) URL")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"available": False, "error": "Playwright is not installed. Run: uv add playwright && uv run playwright install chromium"}
    shot = Path(tempfile.mkdtemp(prefix="shark-shot-")) / "page.png"
    console, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("console", lambda m: m.type in ("error", "warning") and console.append({"level": m.type, "message": m.text[:500]}))
            page.on("pageerror", lambda e: console.append({"level": "error", "message": str(e)[:500]}))
            page.on("requestfailed", lambda r: failed.append({"url": r.url[:300], "error": (r.failure or "")[:200]}))
            page.on("response", lambda r: r.status >= 400 and failed.append({"url": r.url[:300], "error": f"HTTP {r.status}"}))
            response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page.screenshot(path=str(shot), full_page=False)
            text = page.inner_text("body")[:1500] if page.query_selector("body") else ""
            return {"available": True, "url": page.url, "status": response.status if response else None, "title": page.title(),
                    "console": console[:30], "failed_requests": failed[:30], "screenshot": str(shot), "text": text}
        finally:
            browser.close()
