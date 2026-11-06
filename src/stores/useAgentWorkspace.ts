import { create } from 'zustand';
import { useProjectStore } from './useProjectStore';
import { EXPECTED_RUNTIME, restartBackend, sharkBackend, sharkWorkspace, sharkWorkflows, type AgentTask, type ChangePreview, type ImpactReport, type ProviderStatus, type SlashCommand, type TaskEvent } from '../lib/sharkBackend';

export interface RunOptions { provider: string; model: string; apiKey?: string; effort?: string; mode?: string; skills?: string[]; customSkills?: string[]; group?: string; workflow?: boolean }
interface AgentWorkspace {
  tasks: AgentTask[]; activeId: string; events: TaskEvent[]; cursor: number;
  historyEvents: Record<string, TaskEvent[]>; loadHistory(ids: string[]): Promise<void>;
  impact: ImpactReport | null; proposal: ChangePreview | null;
  providers: ProviderStatus[]; commands: SlashCommand[]; catalog: Record<string, { id: string; label: string }[]>; loadModels(provider: string): Promise<void>; error: string; busy: boolean; connected: boolean;
  connect(): Promise<void>; select(id: string): Promise<void>; fresh(): void; remove(id: string): Promise<void>;
  run(goal: string, options: RunOptions): Promise<boolean>;
  spawn(goal: string, options: RunOptions): Promise<void>; refreshTasks(): Promise<void>;
  poll(): Promise<void>; review(): Promise<void>; apply(): Promise<void>; cancel(): Promise<void>; clearError(): void;
}
const message = (e: unknown) => e instanceof Error ? e.message : String(e);
function findProposalTask(tasks: AgentTask[], activeId: string): AgentTask | undefined {
  const byId = new Map(tasks.map(t => [t.id, t]));
  let cur = byId.get(activeId);
  if (cur?.proposal_id) return cur;
  const seen = new Set<string>();
  while (cur && !seen.has(cur.id) && seen.size < 50) {
    seen.add(cur.id);
    if (cur.status === 'review' && cur.proposal_id) return cur;
    if (cur.status === 'applied') return undefined;
    const m = /^\[context\]\r?\n[\s\S]*?PreviousId:\s*(\S+)/.exec(cur.goal);
    const prevId = m?.[1]?.trim() ?? '';
    cur = prevId ? byId.get(prevId) : undefined;
  }
  return undefined;
}
let generation = 0;
let taskRevision = 0;
let selectionRevision = 0;
const polling = new Map<string, Promise<void>>();
const historyLoading = new Set<string>();

export const useAgentWorkspace = create<AgentWorkspace>((set, get) => ({
  historyEvents: {}, tasks: [], activeId: '', events: [], cursor: 0, impact: null, proposal: null, providers: [], commands: [], catalog: {},
  loadModels: async provider => {
    if (get().catalog[provider] || !useProjectStore.getState().root || useProjectStore.getState().kind !== 'native') return;
    try { const r = await sharkWorkspace.models(provider); set(s => ({ catalog: { ...s.catalog, [provider]: r.models } })); } catch { /* keep static suggestions */ }
  },
  error: '', busy: false, connected: false,
  connect: async () => {
    const token = ++generation;
    taskRevision++;
    selectionRevision++;
    historyLoading.clear();
    set({ connected: false, historyEvents: {}, tasks: [], activeId: '', events: [], cursor: 0, proposal: null, impact: null, error: '' });
    try {
      const caps = await sharkBackend.capabilities() as { runtime?: { version?: number } };
      if ((caps.runtime?.version ?? 1) < EXPECTED_RUNTIME) {
        // A backend started before an app update rejects new parameters; restart it transparently once.
        await restartBackend();
        const again = await sharkBackend.capabilities() as { runtime?: { version?: number } };
        if ((again.runtime?.version ?? 1) < EXPECTED_RUNTIME) throw new Error('The Shark backend is older than this app. Run npm run backend:setup, then restart the backend.');
      }
      const [result, providers, commands] = await Promise.all([sharkWorkspace.tasks(), sharkWorkspace.providers().catch(() => ({ providers: [] })), sharkWorkspace.commands().catch(() => ({ commands: [] }))]);
      if (token === generation) set({ connected: true, tasks: result.tasks, providers: providers.providers, commands: commands.commands });
    } catch (e) { if (token === generation) set({ error: message(e) }); }
  },
  select: async id => {
    selectionRevision++;
    const current = get();
    if (current.activeId && current.events.length) set(s => ({historyEvents: {...s.historyEvents, [current.activeId]: current.events}}));
    const cached = current.historyEvents[id] ?? [];
    set({ activeId: id, events: cached, cursor: cached.at(-1)?.sequence ?? 0, proposal: null, impact: null, error: '' });
    await get().poll(); await get().review();
  },
  fresh: () => {selectionRevision++; set({ activeId: '', events: [], cursor: 0, proposal: null, impact: null, error: '' });},
  remove: async id => {
    try {
      const tasks = get().tasks;
      const byId = new Map(tasks.map(t => [t.id, t]));
      const toDelete = new Set<string>([id]);
      let cur = id;
      while (cur && byId.has(cur) && toDelete.size < 50) {
        const goal = byId.get(cur)!.goal;
        const m = /^\[context\]\r?\n[\s\S]*?PreviousId:\s*(\S+)/.exec(goal);
        let prevId = m?.[1]?.trim() ?? '';
        if (!prevId) {
          const prevReq = /^\[context\]\r?\n[\s\S]*?Previous request:\s*(.*)/.exec(goal)?.[1]?.trim() ?? '';
          if (prevReq) {
            const idx = tasks.findIndex(t => t.id === cur);
            const pool = idx >= 0 ? tasks.slice(idx + 1) : tasks.filter(t => t.id !== cur);
            prevId = pool.find(t => t.goal.replace(/^\[context\]\r?\n[\s\S]*?\[\/context\]\r?\n/, '').split('\n')[0].slice(0, 300).trim() === prevReq)?.id ?? '';
          }
        }
        if (!prevId || toDelete.has(prevId)) break;
        toDelete.add(prevId);
        cur = prevId;
      }
      taskRevision++;
      await Promise.all([...toDelete].map(tid => sharkWorkspace.deleteTask(tid).catch(() => {})));
      taskRevision++;
      set(s => ({
        tasks: s.tasks.filter(t => !toDelete.has(t.id)),
        ...(toDelete.has(s.activeId) ? { activeId: '', events: [], cursor: 0, proposal: null, impact: null } : {}),
      }));
    } catch (e) { set({ error: message(e) }); }
  },
  run: async (goal, { provider, model, apiKey, effort, mode, skills, customSkills, group, workflow }) => {
    set({ busy: true, error: '' });
    const prev = get();
    let createdTaskId = '';
    try {
      const created = workflow && mode !== 'chat' ? await sharkWorkflows.create(goal, { provider, model, ...(effort ? { effort } : {}), ...(mode ? { mode } : {}), skills: skills ?? [], custom_skills: customSkills ?? [], ...(group ? { group } : {}) }) : null;
      const task = created?.task ?? await sharkWorkspace.createTask(goal);
      createdTaskId = task.id;
      const optimisticTask: AgentTask = { ...task, status: 'running', engine: provider, model, ...(mode ? { mode } : {}) };
      taskRevision++;
      selectionRevision++;
      set(s => ({
        historyEvents: s.activeId && s.events.length ? { ...s.historyEvents, [s.activeId]: s.events } : s.historyEvents,
        tasks: [optimisticTask, ...s.tasks.filter(t => t.id !== task.id)],
        activeId: task.id,
        events: [],
        cursor: 0,
        proposal: null,
        impact: null,
      }));
      if (created) await sharkWorkflows.start(created.workflow.id, apiKey);
      else await sharkWorkspace.start(task.id, { provider, model, ...(apiKey ? { api_key: apiKey } : {}), ...(effort ? { effort } : {}), mode, skills, custom_skills: customSkills, ...(group ? { group } : {}) });
      await get().poll();
      return true;
    } catch (e) {
      if (createdTaskId) {
        await sharkWorkspace.deleteTask(createdTaskId).catch(() => {});
        taskRevision++;
        selectionRevision++;
        set(s => ({
          tasks: s.tasks.filter(t => t.id !== createdTaskId),
          activeId: prev.activeId,
          events: prev.events,
          cursor: prev.cursor,
          proposal: prev.proposal,
          impact: prev.impact,
          error: message(e),
        }));
      } else {
        set({ error: message(e) });
      }
      return false;
    }
    finally { set({ busy: false }); }
  },
  spawn: async (goal, o) => {
    try {
      const created = o.workflow && o.mode !== 'chat' ? await sharkWorkflows.create(goal, { provider: o.provider, model: o.model, ...(o.effort ? { effort: o.effort } : {}), ...(o.mode ? { mode: o.mode } : {}), skills: o.skills ?? [], custom_skills: o.customSkills ?? [], ...(o.group ? { group: o.group } : {}) }) : null;
      const task = created?.task ?? await sharkWorkspace.createTask(goal);
      taskRevision++;
      set(s => ({ tasks: [task, ...s.tasks] }));
      if (created) await sharkWorkflows.start(created.workflow.id, o.apiKey);
      else await sharkWorkspace.start(task.id, { provider: o.provider, model: o.model, ...(o.apiKey ? { api_key: o.apiKey } : {}), ...(o.effort ? { effort: o.effort } : {}), mode: o.mode, skills: o.skills, custom_skills: o.customSkills, group: o.group });
    } catch (e) { set({ error: message(e) }); }
  },
  refreshTasks: async () => {
    const token = generation, revision = taskRevision;
    try {
      const r = await sharkWorkspace.tasks();
      if (token === generation && revision === taskRevision) {
        set(s => {
          const prevById = new Map(s.tasks.map(t => [t.id, t]));
          const merged = r.tasks.map(next => {
            const prev = prevById.get(next.id);
            return prev && prev.goal.length > next.goal.length ? { ...next, goal: prev.goal } : next;
          });
          return { tasks: [...merged, ...s.tasks.filter(t => !r.tasks.some(next => next.id === t.id))] };
        });
        taskRevision++;
      }
    } catch { /* backend offline: keep the last known list */ }
  },
  loadHistory: async ids => {
    const token = generation;
    await Promise.all(ids.map(async id => {
      if (get().historyEvents[id] || historyLoading.has(id)) return;
      historyLoading.add(id);
      try {
        const events: TaskEvent[] = [];
        let cursor = 0;
        while (true) {
          const page = await sharkWorkspace.events(id, cursor);
          if (token !== generation) return;
          events.push(...page.events);
          if (!page.has_more) break;
          if (page.next_cursor <= cursor) throw new Error('Conversation event cursor did not advance.');
          cursor = page.next_cursor;
        }
        set(s => ({historyEvents: {...s.historyEvents, [id]: events}}));
      } catch (e) { if (token === generation) set({error: message(e)}); }
      finally { historyLoading.delete(id); }
    }));
  },
  poll: async () => {
    const id = get().activeId; if (!id) return;
    const selection = selectionRevision;
    const key = `${generation}:${selection}:${id}`;
    const existing = polling.get(key); if (existing) return existing;
    const token = generation;
    const update = (async () => {
      try {
        let task = await sharkWorkspace.task(id);
        const drain = async () => {
          while (true) {
            const cursor = get().cursor;
            const page = await sharkWorkspace.events(id, cursor);
            if (get().activeId !== id || generation !== token || selectionRevision !== selection) return false;
            set(s => {
              const fresh = page.events.filter(e => e.sequence > (s.events.at(-1)?.sequence ?? 0));
              return fresh.length ? {events: [...s.events, ...fresh], cursor: page.next_cursor} : page.next_cursor !== s.cursor ? {cursor: page.next_cursor} : {};
            });
            if (!page.has_more) return true;
            if (page.next_cursor <= cursor) throw new Error('Conversation event cursor did not advance.');
          }
        };
        if (!await drain()) return;
        const latest = await sharkWorkspace.task(id);
        if (get().activeId !== id || generation !== token || selectionRevision !== selection) return;
        if (task.status === 'running' && latest.status !== 'running' && !await drain()) return;
        task = latest;
        taskRevision++;
        set(s => ({
          tasks: s.tasks.some(t => t.id === id) ? s.tasks.map(t => t.id === id ? task : t) : [task, ...s.tasks],
          ...(task.status !== 'running' && s.events.length ? { historyEvents: { ...s.historyEvents, [id]: s.events } } : {}),
        }));
        const propTask = task.proposal_id ? task : findProposalTask(get().tasks, id);
        if (propTask?.proposal_id && !get().proposal) await get().review();
      } catch (e) { if (get().activeId === id && generation === token && selectionRevision === selection) set({error: message(e)}); }
    })();
    polling.set(key, update);
    try { await update; } finally { if (polling.get(key) === update) polling.delete(key); }
  },
  review: async () => {
    const id = get().activeId; if (!id) return;
    try {
      const propTask = findProposalTask(get().tasks, id) ?? await sharkWorkspace.task(id);
      if (!propTask?.proposal_id) return;
      const result = await sharkWorkspace.analyze(propTask.proposal_id);
      if (get().activeId === id) set({ proposal: result.proposal, impact: result.impact });
    } catch (e) { if (get().activeId === id) set({ error: message(e) }); }
  },
  apply: async () => {
    const id = get().activeId; if (!id) return;
    const targetId = findProposalTask(get().tasks, id)?.id ?? id;
    set({ busy: true, error: '' });
    try {
      const paths = get().proposal?.files.map(f => f.path) || [];
      if (useProjectStore.getState().tabs.some(t => paths.includes(t.path) && t.content !== t.saved))
        throw new Error('Save or discard your edits in the affected files first, then apply again.');
      const result = await sharkWorkspace.apply(targetId);
      set(s => ({ proposal: result.proposal, tasks: s.tasks.map(t => t.id === targetId ? result.task : t) }));
      await get().poll();
      await useProjectStore.getState().refreshFromDisk(paths);
    } catch (e) { set({ error: message(e) }); }
    finally { set({ busy: false }); }
  },
  cancel: async () => { try { await sharkWorkspace.cancel(get().activeId); await get().poll(); } catch (e) { set({ error: message(e) }); } },
  clearError: () => set({ error: '' }),
}));
