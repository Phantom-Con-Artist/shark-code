import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Maximize2, Minus, Plus, Redo2, Undo2, LayoutGrid } from 'lucide-react';
import { useAutomata } from '../../stores/useAutomata';
import type { AutomataNode, ComponentSpec } from '../../lib/automata';
import { ComponentIcon } from './icons';

export const DRAG_TYPE = 'application/x-shark-component';
const W = 220, HEAD = 34, ROW = 24;
const nodeHeight = (spec?: ComponentSpec) => 64 + Math.max(0, (spec?.outputs.length ?? 1) - 1) * ROW;
const outY = (spec: ComponentSpec | undefined, port: string) => { const n = spec?.outputs.length ?? 1; return n <= 1 ? 32 : HEAD + 8 + Math.max(0, spec!.outputs.indexOf(port)) * ROW; };
const edgePath = (x1: number, y1: number, x2: number, y2: number) => { const d = Math.max(50, Math.abs(x2 - x1) / 2); return `M${x1},${y1} C${x1 + d},${y1} ${x2 - d},${y2} ${x2},${y2}`; };

let viewApi: { center(): { x: number; y: number }; reveal(x: number, y: number): void } = { center: () => ({ x: 120, y: 120 }), reveal: () => {} };
export const canvasCenter = () => viewApi.center();
export const revealOnCanvas = (x: number, y: number) => viewApi.reveal(x, y);

function summary(node: AutomataNode, spec?: ComponentSpec) {
  const p = spec?.params.find(x => x.required && x.kind !== 'bool') ?? spec?.params[0];
  const v = p ? node.params[p.name] : '';
  return typeof v === 'string' ? v.replace(/\s+/g, ' ').slice(0, 44) : '';
}

export function Canvas() {
  const a = useAutomata();
  const g = a.graph!;
  const ref = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ x: 40, y: 40, z: 1 });
  const [draft, setDraft] = useState<{ from: string; port: string; x: number; y: number } | null>(null);
  const specs = useMemo(() => new Map(a.catalog.map(c => [c.type, c])), [a.catalog]);
  const nodes = useMemo(() => new Map(g.nodes.map(n => [n.id, n])), [g.nodes]);

  const toWorld = useCallback((cx: number, cy: number) => { const r = ref.current!.getBoundingClientRect(); return { x: (cx - r.left - view.x) / view.z, y: (cy - r.top - view.y) / view.z }; }, [view]);
  useEffect(() => {
    viewApi = {
      center: () => { const r = ref.current?.getBoundingClientRect(); return r ? toWorld(r.left + r.width / 2 - W / 2, r.top + r.height / 2 - 30) : { x: 120, y: 120 }; },
      reveal: (x, y) => setView(v => {
        const r = ref.current?.getBoundingClientRect(); if (!r) return v;
        const margin = 24, left = v.x + x * v.z, top = v.y + y * v.z, right = left + W * v.z, bottom = top + 100 * v.z;
        let dx = 0, dy = 0;
        if (left < margin) dx = margin - left; else if (right > r.width - margin) dx = r.width - margin - right;
        if (top < margin) dy = margin - top; else if (bottom > r.height - margin) dy = r.height - margin - bottom;
        return dx || dy ? { ...v, x: v.x + dx, y: v.y + dy } : v;
      }),
    };
  }, [toWorld]);

  const fit = useCallback(() => {
    const r = ref.current?.getBoundingClientRect(); if (!r || !g.nodes.length) { setView({ x: 40, y: 40, z: 1 }); return; }
    const x0 = Math.min(...g.nodes.map(n => n.x)), y0 = Math.min(...g.nodes.map(n => n.y)), x1 = Math.max(...g.nodes.map(n => n.x + W)), y1 = Math.max(...g.nodes.map(n => n.y + 100));
    const z = Math.min(1.1, Math.max(0.3, Math.min((r.width - 80) / (x1 - x0), (r.height - 80) / (y1 - y0))));
    setView({ z, x: (r.width - (x1 - x0) * z) / 2 - x0 * z, y: (r.height - (y1 - y0) * z) / 2 - y0 * z });
  }, [g.nodes]);
  useEffect(() => { fit(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [g.id]);

  const zoomAt = (factor: number, cx?: number, cy?: number) => setView(v => {
    const r = ref.current!.getBoundingClientRect(); const px = (cx ?? r.left + r.width / 2) - r.left, py = (cy ?? r.top + r.height / 2) - r.top;
    const z = Math.min(1.6, Math.max(0.25, v.z * factor)); return { z, x: px - (px - v.x) * (z / v.z), y: py - (py - v.y) * (z / v.z) };
  });
  useEffect(() => {
    const el = ref.current!; const wheel = (e: WheelEvent) => { e.preventDefault(); zoomAt(e.deltaY < 0 ? 1.1 : 0.9, e.clientX, e.clientY); };
    el.addEventListener('wheel', wheel, { passive: false }); return () => el.removeEventListener('wheel', wheel);
  }, []);

  const backgroundDown = (e: React.PointerEvent) => {
    if (e.button !== 0 && e.button !== 1) return;
    if (!e.shiftKey) a.select([]);
    const start = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => setView(v => ({ ...v, x: start.vx + ev.clientX - start.x, y: start.vy + ev.clientY - start.y }));
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  };

  const nodeDown = (e: React.PointerEvent, n: AutomataNode) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest('[data-port]')) return;
    e.stopPropagation();
    const ids = a.selected.includes(n.id) ? (e.shiftKey ? a.selected.filter(i => i !== n.id) : a.selected) : e.shiftKey ? [...a.selected, n.id] : [n.id];
    a.select(ids); useAutomata.setState({ dock: useAutomata.getState().dock === 'run' || useAutomata.getState().dock === 'code' ? useAutomata.getState().dock : 'inspector' });
    let last = { x: e.clientX, y: e.clientY }, moved = false;
    const move = (ev: PointerEvent) => {
      if (!moved) { if (Math.hypot(ev.clientX - last.x, ev.clientY - last.y) < 3) return; moved = true; a.mark(); }
      useAutomata.getState().moveNodes(ids, (ev.clientX - last.x) / view.z, (ev.clientY - last.y) / view.z); last = { x: ev.clientX, y: ev.clientY };
    };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  };

  const portDown = (e: React.PointerEvent, from: string, port: string) => {
    e.stopPropagation(); e.preventDefault();
    const move = (ev: PointerEvent) => { const w = toWorld(ev.clientX, ev.clientY); setDraft({ from, port, ...w }); };
    const up = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); setDraft(null);
      const hit = document.elementFromPoint(ev.clientX, ev.clientY)?.closest<HTMLElement>('[data-in]');
      if (hit?.dataset.in) a.connect(from, port, hit.dataset.in);
    };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up); move(e.nativeEvent);
  };

  const drop = (e: React.DragEvent) => {
    const type = e.dataTransfer.getData(DRAG_TYPE); if (!type) return; e.preventDefault();
    const w = toWorld(e.clientX, e.clientY); a.addNode(type, w.x - W / 2, w.y - 20);
  };

  const key = (e: React.KeyboardEvent) => {
    if ((e.target as HTMLElement).closest('input, textarea, select, .monaco-editor')) return;
    const mod = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
    if (k === 'delete' || k === 'backspace') { e.preventDefault(); a.removeSelected(); }
    else if (mod && k === 'z') { e.preventDefault(); if (e.shiftKey) a.redo(); else a.undo(); }
    else if (mod && k === 'y') { e.preventDefault(); a.redo(); }
    else if (mod && k === 'd') { e.preventDefault(); a.duplicateSelected(); }
    else if (mod && k === 'a') { e.preventDefault(); a.select(g.nodes.map(n => n.id)); }
    else if (k === 'f' && !mod) fit();
  };

  const run = a.run;
  const active = (id: string, port: string) => run?.nodes[id]?.status === 'succeeded' && run.nodes[id].port === port;
  const pos = (id: string, port?: string, input?: boolean) => { const n = nodes.get(id)!; const s = specs.get(n.type); return input ? { x: n.x, y: n.y + 32 } : { x: n.x + W, y: n.y + outY(s, port ?? 'out') }; };

  return <div className="cv" ref={ref} tabIndex={0} onKeyDown={key} onPointerDown={backgroundDown} onDragOver={e => { if (e.dataTransfer.types.includes(DRAG_TYPE)) e.preventDefault(); }} onDrop={drop}
    style={{ backgroundPosition: `${view.x}px ${view.y}px`, backgroundSize: `${24 * view.z}px ${24 * view.z}px` }} aria-label="Automation canvas">
    <div className="cv-world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.z})` }}>
      <svg className="cv-edges" width="1" height="1">
        {g.edges.filter(e => nodes.has(e.from) && nodes.has(e.to)).map(e => { const p1 = pos(e.from, e.from_port), p2 = pos(e.to, undefined, true), d = edgePath(p1.x, p1.y, p2.x, p2.y);
          return <g key={e.id} className={`cv-edge ${a.selectedEdge === e.id ? 'sel' : ''} ${active(e.from, e.from_port) ? 'live' : ''}`}>
            <path d={d} className="hit" onPointerDown={ev => { ev.stopPropagation(); a.select([], e.id); (ref.current as HTMLElement).focus(); }} /><path d={d} className="line" />
          </g>; })}
        {draft && nodes.has(draft.from) && <path className="cv-draft" d={edgePath(pos(draft.from, draft.port).x, pos(draft.from, draft.port).y, draft.x, draft.y)} />}
      </svg>
      {g.nodes.map(n => { const spec = specs.get(n.type); const st = run?.nodes[n.id]?.status; const sel = a.selected.includes(n.id);
        return <div key={n.id} className={`cv-node ${sel ? 'sel' : ''} ${st ? 's-' + st : ''} ${spec ? '' : 'unknown'}`} style={{ left: n.x, top: n.y, width: W, minHeight: nodeHeight(spec) }} onPointerDown={e => nodeDown(e, n)} data-node={n.id}>
          {spec?.inputs !== false && <span className="cv-port in" data-in={n.id} data-port="in" title="Input" />}
          <div className="cv-head"><span className="cv-ico"><ComponentIcon name={spec?.icon ?? 'box'} size={13} /></span><span className="cv-title ellipsis">{n.label || spec?.label || n.type}</span>
            {st && <span className={`cv-state ${st}`} title={run?.nodes[n.id]?.error ?? st}>{st === 'succeeded' ? '✓' : st === 'failed' ? '!' : st === 'waiting' ? '?' : st === 'skipped' ? '–' : ''}</span>}</div>
          <div className="cv-body"><span className="cv-sub ellipsis">{spec ? summary(n, spec) || spec.description.slice(0, 44) : `Unknown component ${n.type}`}</span><small className="ellipsis">{n.id}{(run?.nodes[n.id]?.attempts ?? 0) > 1 ? ` · attempt ${run?.nodes[n.id]?.attempts}` : ''}</small></div>
          {(spec?.outputs ?? ['out']).map(port => <span key={port} className={`cv-port out ${active(n.id, port) ? 'live' : ''}`} data-port="out" style={{ top: outY(spec, port) - 6 }} onPointerDown={e => portDown(e, n.id, port)} title={`Output ${port}`}>
            {(spec?.outputs.length ?? 1) > 1 && <em>{port}</em>}</span>)}
        </div>; })}
    </div>
    {!g.nodes.length && <div className="cv-empty"><strong>Empty canvas</strong><span>Drag a component from the list, or tell Shark what to automate.</span></div>}
    <div className="cv-tools" onPointerDown={e => e.stopPropagation()}>
      <button className="icon-btn sm" aria-label="Undo" title="Undo · Ctrl Z" disabled={!a.past.length} onClick={a.undo}><Undo2 size={14} /></button>
      <button className="icon-btn sm" aria-label="Redo" title="Redo · Ctrl Y" disabled={!a.future.length} onClick={a.redo}><Redo2 size={14} /></button>
      <span className="cv-sep" />
      <button className="icon-btn sm" aria-label="Zoom out" onClick={() => zoomAt(0.85)}><Minus size={14} /></button>
      <span className="cv-zoom">{Math.round(view.z * 100)}%</span>
      <button className="icon-btn sm" aria-label="Zoom in" onClick={() => zoomAt(1.18)}><Plus size={14} /></button>
      <button className="icon-btn sm" aria-label="Fit to screen" title="Fit · F" onClick={fit}><Maximize2 size={14} /></button>
      <button className="icon-btn sm" aria-label="Tidy layout" title="Tidy layout" onClick={() => { a.tidy(); setTimeout(fit, 30); }}><LayoutGrid size={14} /></button>
    </div>
  </div>;
}
