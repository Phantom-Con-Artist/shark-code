import { create } from 'zustand';
import { useProjectStore } from './useProjectStore';
import { sharkBackend, sharkWorkspace, type AgentTask, type ChangePreview, type ImpactReport, type TaskEvent } from '../lib/sharkBackend';

interface AgentWorkspace {
  tasks: AgentTask[]; activeId: string; events: TaskEvent[]; cursor: number;
  impact: ImpactReport | null;
  proposal: ChangePreview | null; error: string; busy: boolean; connected: boolean;
  connect(): Promise<void>; select(id: string): Promise<void>; fresh(): void;
  run(goal: string, model: string): Promise<void>;
  poll(): Promise<void>; review(): Promise<void>; apply(): Promise<void>; cancel(): Promise<void>; clearError(): void;
}
let generation = 0;
export const useAgentWorkspace = create<AgentWorkspace>((set, get) => ({
  tasks: [], activeId: '', events: [], cursor: 0, impact: null, proposal: null,
  error: '', busy: false, connected: false,
  connect: async () => {
    const token = ++generation;
    set({ connected: false, tasks: [], activeId: '', events: [], proposal: null, impact: null, error: '' });
    try {
      await sharkBackend.capabilities();
      const result = await sharkWorkspace.tasks();
      if (token === generation) set({ connected: true, tasks: result.tasks });
    } catch (e) { if (token === generation) set({ error: e instanceof Error ? e.message : String(e) }); }
  },
  select: async id => {
    set({ activeId: id, events: [], cursor: 0, proposal: null, impact: null, error: '' });
    await get().poll(); await get().review();
  },
  fresh: () => set({ activeId: '', events: [], cursor: 0, proposal: null, impact: null, error: '' }),
  run: async (goal, model) => {
    set({ busy: true, error: '' });
    try {
      const task = await sharkWorkspace.createTask(goal);
      set(s => ({ tasks: [task, ...s.tasks], activeId: task.id, events: [], cursor: 0, proposal: null, impact: null }));
      await sharkWorkspace.start(task.id, model);
      await get().poll();
    } catch (e) { set({ error: e instanceof Error ? e.message : String(e) }); }
    finally { set({ busy: false }); }
  },
  poll: async () => {
    const { activeId: id, cursor } = get(); if (!id) return;
    try {
      const [task, page] = await Promise.all([sharkWorkspace.task(id), sharkWorkspace.events(id, cursor)]);
      if (get().activeId !== id) return;
      set(s => ({ tasks: s.tasks.map(t => t.id === id ? task : t),
        events: [...s.events, ...page.events.filter(e => !s.events.some(old => old.sequence === e.sequence))], cursor: page.next_cursor }));
      if (task.proposal_id && !get().proposal) await get().review();
    } catch (e) { if (get().activeId === id) set({ error: e instanceof Error ? e.message : String(e) }); }
  },
  review: async () => {
    const id = get().activeId; if (!id) return;
    try {
      const task = await sharkWorkspace.task(id); if (!task.proposal_id) return;
      const result = await sharkWorkspace.analyze(task.proposal_id);
      if (get().activeId === id) set({ proposal: result.proposal, impact: result.impact });
    } catch (e) { if (get().activeId === id) set({ error: e instanceof Error ? e.message : String(e) }); }
  },
  apply: async () => {
    const id = get().activeId; if (!id) return;
    set({ busy: true, error: '' });
    try {
      const paths = get().proposal?.files.map(f => f.path) || [];
      const project = useProjectStore.getState();
      if (project.tabs.some(t => paths.includes(t.path) && t.content !== t.saved)) {
        throw new Error('Save your unsaved edits in the affected files before applying this proposal. The source versions will then be checked again.');
      }
      const result = await sharkWorkspace.apply(id);
      set(s => ({ proposal: result.proposal, tasks: s.tasks.map(t => t.id === id ? result.task : t) }));
      await get().poll();
      await useProjectStore.getState().refreshFromDisk(paths);
    } catch (e) { set({ error: e instanceof Error ? e.message : String(e) }); }
    finally { set({ busy: false }); }
  },
  cancel: async () => { try { await sharkWorkspace.cancel(get().activeId); await get().poll(); } catch (e) { set({ error: e instanceof Error ? e.message : String(e) }); } },
  clearError: () => set({ error: '' }),
}));
