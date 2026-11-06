import { create } from 'zustand';
import { sharkAutomata, type AutomataEdge, type AutomataNode, type ComponentSpec, type Graph, type Run, type Validation, type WorkflowSummary } from '../lib/automata';
import { useSettings } from './useSettings';

export type Dock = 'inspector' | 'run' | 'code' | 'intelligence' | 'tests';
type Snapshot = Pick<Graph, 'nodes' | 'edges' | 'name'>;
const HISTORY = 60;
const NODE_W = 220;

interface AutomataState {
  catalog: ComponentSpec[]; templates: Graph[]; problems: { file: string; error: string }[]; workflows: WorkflowSummary[];
  graph: Graph | null; savedVersion: string | null; dirty: boolean; saving: boolean; external: boolean; refreshedByShark: number;
  selected: string[]; selectedEdge: string | null; validation: Validation | null;
  past: Snapshot[]; future: Snapshot[];
  run: Run | null; running: boolean; dock: Dock; dockOpen: boolean; code: { filename: string; code: string } | null;
  error: string; loaded: boolean;
  init(): Promise<void>; refresh(): Promise<void>; newGraph(name?: string): Promise<void>; newFromTemplate(templateId: string): Promise<void>; open(id: string): Promise<void>; remove(id: string): Promise<void>;
  save(force?: boolean): Promise<void>; reload(): Promise<void>;
  addNode(type: string, x: number, y: number): string | null; moveNodes(ids: string[], dx: number, dy: number): void; mark(): void;
  patchNode(id: string, patch: Partial<AutomataNode>): void; setParam(id: string, name: string, value: unknown): void;
  select(ids: string[], edge?: string | null): void; removeSelected(): void; duplicateSelected(): void;
  connect(from: string, port: string, to: string): void; removeEdge(id: string): void; rename(name: string): void;
  undo(): void; redo(): void; tidy(): void;
  start(mode: 'run' | 'test'): Promise<void>; poll(): Promise<void>; respond(decision: 'approve' | 'reject' | 'answer', answer?: string): Promise<void>;
  resume(retry: boolean): Promise<void>; cancel(): Promise<void>; showDock(dock: Dock): void; generateCode(): Promise<void>; exportCode(): Promise<void>;
  setError(message: string): void;
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'workflow';
let validateTimer: ReturnType<typeof setTimeout> | undefined;
let saveTimer: ReturnType<typeof setTimeout> | undefined;
let pollTimer: ReturnType<typeof setTimeout> | undefined;

export const useAutomata = create<AutomataState>((set, get) => {
  const snapshot = (): Snapshot | null => { const g = get().graph; return g ? { nodes: structuredClone(g.nodes), edges: structuredClone(g.edges), name: g.name } : null; };
  const push = () => { const s = snapshot(); if (s) set(st => ({ past: [...st.past.slice(-HISTORY + 1), s], future: [] })); };
  const edit = (fn: (g: Graph) => Graph, history = true) => {
    const g = get().graph; if (!g) return;
    if (history) push();
    set({ graph: fn(g), dirty: true });
    clearTimeout(validateTimer); validateTimer = setTimeout(() => void validateNow(), 400);
    clearTimeout(saveTimer); saveTimer = setTimeout(() => void get().save(), 1200);
  };
  const validateNow = async () => { const g = get().graph; if (!g) return; try { set({ validation: await sharkAutomata.validate(g) }); } catch { /* backend offline */ } };
  const catalogOf = (type: string) => get().catalog.find(c => c.type === type);
  const loadGraph = (graph: Graph, version: string) => {
    set({ graph, savedVersion: version, dirty: false, external: false, selected: [], selectedEdge: null, past: [], future: [], run: null, code: null, error: '' });
    void validateNow();
  };

  return {
    catalog: [], templates: [], problems: [], workflows: [], graph: null, savedVersion: null, dirty: false, saving: false, external: false, refreshedByShark: 0,
    selected: [], selectedEdge: null, validation: null, past: [], future: [], run: null, running: false, dock: 'inspector', dockOpen: false, code: null, error: '', loaded: false,

    async init() {
      try {
        const [cat, list] = await Promise.all([sharkAutomata.catalog(), sharkAutomata.list()]);
        set({ catalog: cat.components, templates: cat.templates ?? [], problems: cat.problems, workflows: list.workflows, loaded: true, error: '' });
        const last = localStorage.getItem('shark.automata.last');
        const first = list.workflows.find(w => w.id === last && !w.broken) ?? list.workflows.find(w => !w.broken);
        if (first && !get().graph) { const r = await sharkAutomata.get(first.id); loadGraph(r.graph, r.version); }
      } catch (e) { set({ error: message(e), loaded: true }); }
    },

    async refresh() {
      try {
        const [cat, list] = await Promise.all([sharkAutomata.catalog(), sharkAutomata.list()]);
        const same = JSON.stringify(cat.components) === JSON.stringify(get().catalog);
        set({ workflows: list.workflows, templates: cat.templates ?? get().templates, ...(same ? {} : { catalog: cat.components }), problems: cat.problems });
        const { graph, savedVersion, dirty } = get();
        const mine = graph && list.workflows.find(w => w.id === graph.id);
        if (graph && !mine && savedVersion) { set({ external: true }); return; }
        if (mine && savedVersion && mine.version !== savedVersion && !get().saving) {
          if (dirty) set({ external: true });
          else { const r = await sharkAutomata.get(graph!.id); loadGraph(r.graph, r.version); set({ refreshedByShark: Date.now() }); }
        }
      } catch { /* keep the last known state */ }
    },

    async newGraph(name = 'Untitled workflow') {
      const taken = new Set(get().workflows.map(w => w.id)); let id = slug(name), n = 2;
      while (taken.has(id)) id = `${slug(name)}-${n++}`;
      const graph: Graph = { id, name, description: '', nodes: [], edges: [] };
      try { const r = await sharkAutomata.save(graph); loadGraph(graph, r.version); localStorage.setItem('shark.automata.last', id); await get().refresh(); }
      catch (e) { set({ error: message(e) }); }
    },

    async newFromTemplate(templateId) {
      const tpl = get().templates.find(t => t.id === templateId);
      if (!tpl) return;
      const taken = new Set(get().workflows.map(w => w.id)); let id = slug(tpl.id), n = 2;
      while (taken.has(id)) id = `${slug(tpl.id)}-${n++}`;
      const graph: Graph = {
        id,
        name: tpl.name,
        description: tpl.description ?? '',
        nodes: structuredClone(tpl.nodes),
        edges: structuredClone(tpl.edges),
      };
      try { const r = await sharkAutomata.save(graph); loadGraph(graph, r.version); localStorage.setItem('shark.automata.last', id); await get().refresh(); }
      catch (e) { set({ error: message(e) }); }
    },

    async open(id) {
      if (get().dirty) await get().save();
      try { const r = await sharkAutomata.get(id); loadGraph(r.graph, r.version); localStorage.setItem('shark.automata.last', id); }
      catch (e) { set({ error: message(e) }); }
    },

    async remove(id) {
      try {
        await sharkAutomata.remove(id);
        if (get().graph?.id === id) set({ graph: null, savedVersion: null, dirty: false, run: null, validation: null });
        await get().refresh();
      } catch (e) { set({ error: message(e) }); }
    },

    async save(force = false) {
      const { graph, savedVersion, saving } = get();
      if (!graph || saving || (!get().dirty && !force)) return;
      clearTimeout(saveTimer); set({ saving: true });
      try {
        const r = await sharkAutomata.save(graph, force ? undefined : savedVersion ?? undefined);
        const moved = get().graph !== graph;
        set({ savedVersion: r.version, dirty: moved, external: false, error: '' });
        if (moved) saveTimer = setTimeout(() => void get().save(), 600);
      } catch (e) {
        const text = message(e);
        set(text.includes('changed on disk') ? { external: true } : { error: text });
      } finally { set({ saving: false }); }
    },

    async reload() {
      const id = get().graph?.id; if (!id) return;
      try { const r = await sharkAutomata.get(id); loadGraph(r.graph, r.version); } catch (e) { set({ error: message(e) }); }
    },

    addNode(type, x, y) {
      const spec = catalogOf(type), g = get().graph;
      if (!spec || !g) return null;
      const base = (type.split('.').pop() ?? 'node').replace(/[^a-zA-Z0-9]/g, '').replace(/^\d+/, '') || 'node';
      const ids = new Set(g.nodes.map(n => n.id)); let n = 1;
      while (ids.has(`${base}${n}`)) n++;
      const id = `${base}${n}`;
      const params: Record<string, unknown> = {}; for (const p of spec.params) params[p.name] = p.default;
      edit(cur => ({ ...cur, nodes: [...cur.nodes, { id, type, x: Math.round(x / 10) * 10, y: Math.round(y / 10) * 10, params }] }));
      set({ selected: [id], selectedEdge: null, dock: 'inspector', dockOpen: true });
      return id;
    },

    moveNodes(ids, dx, dy) { edit(g => ({ ...g, nodes: g.nodes.map(n => ids.includes(n.id) ? { ...n, x: n.x + dx, y: n.y + dy } : n) }), false); },
    mark() { push(); },
    patchNode(id, patch) { edit(g => ({ ...g, nodes: g.nodes.map(n => n.id === id ? { ...n, ...patch } : n) })); },
    setParam(id, name, value) { edit(g => ({ ...g, nodes: g.nodes.map(n => n.id === id ? { ...n, params: { ...n.params, [name]: value } } : n) })); },
    select(ids, edge = null) { set({ selected: ids, selectedEdge: edge }); },

    removeSelected() {
      const { selected, selectedEdge } = get();
      if (selectedEdge) { get().removeEdge(selectedEdge); return; }
      if (!selected.length) return;
      edit(g => ({ ...g, nodes: g.nodes.filter(n => !selected.includes(n.id)), edges: g.edges.filter(e => !selected.includes(e.from) && !selected.includes(e.to)) }));
      set({ selected: [] });
    },

    duplicateSelected() {
      const { selected, graph } = get(); if (!graph || !selected.length) return;
      const ids = new Set(graph.nodes.map(n => n.id)); const map = new Map<string, string>(); const copies: AutomataNode[] = [];
      for (const n of graph.nodes.filter(n => selected.includes(n.id))) {
        const base = n.id.replace(/\d+$/, '') || 'node'; let i = 1; while (ids.has(`${base}${i}`)) i++;
        ids.add(`${base}${i}`); map.set(n.id, `${base}${i}`);
        copies.push({ ...structuredClone(n), id: `${base}${i}`, x: n.x + 40, y: n.y + 40 });
      }
      const edges = graph.edges.filter(e => map.has(e.from) && map.has(e.to)).map((e, k) => ({ ...e, id: `${map.get(e.from)}_${map.get(e.to)}_${k}`, from: map.get(e.from)!, to: map.get(e.to)! }));
      edit(g => ({ ...g, nodes: [...g.nodes, ...copies], edges: [...g.edges, ...edges] }));
      set({ selected: copies.map(c => c.id) });
    },

    connect(from, port, to) {
      const g = get().graph; if (!g || from === to) return;
      const target = g.nodes.find(n => n.id === to), spec = target && catalogOf(target.type);
      if (!spec?.inputs || g.edges.some(e => e.from === from && e.from_port === port && e.to === to)) return;
      // Reject connections that would close a loop.
      const reach = (id: string, seen = new Set<string>()): Set<string> => { for (const e of g.edges) if (e.from === id && !seen.has(e.to)) { seen.add(e.to); reach(e.to, seen); } return seen; };
      if (reach(to).has(from)) { set({ error: 'That connection would make a loop. Connections must flow one way.' }); return; }
      const id = `${from}_${port}_${to}`;
      edit(cur => ({ ...cur, edges: [...cur.edges, { id, from, from_port: port, to } as AutomataEdge] }));
    },

    removeEdge(id) { edit(g => ({ ...g, edges: g.edges.filter(e => e.id !== id) })); set({ selectedEdge: null }); },
    rename(name) { edit(g => ({ ...g, name })); },

    undo() {
      const { past, graph } = get(); const prev = past[past.length - 1]; const cur = snapshot();
      if (!prev || !graph || !cur) return;
      set(st => ({ past: st.past.slice(0, -1), future: [cur, ...st.future], graph: { ...graph, ...prev }, dirty: true }));
      clearTimeout(saveTimer); saveTimer = setTimeout(() => void get().save(), 1200); void validateNow();
    },
    redo() {
      const { future, graph } = get(); const next = future[0]; const cur = snapshot();
      if (!next || !graph || !cur) return;
      set(st => ({ future: st.future.slice(1), past: [...st.past, cur], graph: { ...graph, ...next }, dirty: true }));
      clearTimeout(saveTimer); saveTimer = setTimeout(() => void get().save(), 1200); void validateNow();
    },

    tidy() {
      edit(g => {
        const depth = new Map<string, number>();
        const visit = (id: string, seen: string[] = []): number => {
          if (depth.has(id)) return depth.get(id)!;
          if (seen.includes(id)) return 0;
          const parents = g.edges.filter(e => e.to === id).map(e => e.from);
          const d = parents.length ? Math.max(...parents.map(p => visit(p, [...seen, id]))) + 1 : 0; depth.set(id, d); return d;
        };
        g.nodes.forEach(n => visit(n.id));
        const rows = new Map<number, number>();
        return { ...g, nodes: g.nodes.map(n => { const d = depth.get(n.id) ?? 0, r = rows.get(d) ?? 0; rows.set(d, r + 1); return { ...n, x: 80 + d * (NODE_W + 70), y: 80 + r * 130 }; }) };
      });
    },

    async start(mode) {
      const { graph } = get(); if (!graph) return;
      if (get().dirty) await get().save();
      const s = useSettings.getState();
      try {
        set({ running: true, error: '', dock: 'run', dockOpen: true });
        const run = await sharkAutomata.run(graph, mode, { provider: s.provider, model: s.models[s.provider] ?? '' }, s.keys[s.provider]);
        set({ run }); void get().poll();
      } catch (e) { set({ running: false, error: message(e) }); }
    },

    async poll() {
      clearTimeout(pollTimer);
      const run = get().run; if (!run) { set({ running: false }); return; }
      try {
        const next = await sharkAutomata.runGet(run.id);
        if (get().run?.id !== run.id) return;
        set({ run: next, running: next.status === 'running' });
        if (next.status === 'running' || next.status === 'waiting_human') pollTimer = setTimeout(() => void get().poll(), next.status === 'running' ? 400 : 1200);
      } catch (e) { set({ running: false, error: message(e) }); }
    },

    async respond(decision, answer = '') {
      const run = get().run; if (!run?.gate) return;
      try { set({ run: await sharkAutomata.respond(run.id, run.gate.id, decision, answer), running: true }); void get().poll(); } catch (e) { set({ error: message(e) }); }
    },
    async resume(retry) {
      const run = get().run; if (!run) return;
      try { set({ run: await sharkAutomata.resume(run.id, retry), running: true }); void get().poll(); } catch (e) { set({ error: message(e) }); }
    },
    async cancel() {
      const run = get().run; if (!run) return;
      try { set({ run: await sharkAutomata.cancel(run.id) }); void get().poll(); } catch (e) { set({ error: message(e) }); }
    },
    showDock(dock) { set({ dock, dockOpen: true }); },
    async generateCode() {
      const g = get().graph; if (!g) return;
      try { set({ code: await sharkAutomata.codegen(g), error: '' }); } catch (e) { set({ code: null, error: message(e) }); }
    },
    async exportCode() {
      const g = get().graph; if (!g) return;
      try { if (get().dirty) await get().save(); set({ code: await sharkAutomata.exportCode(g), error: '' }); void import('./useProjectStore').then(m => m.useProjectStore.getState().initialize()); } catch (e) { set({ error: message(e) }); }
    },
    setError(m) { set({ error: m }); },
  };
});
