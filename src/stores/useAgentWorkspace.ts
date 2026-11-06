import { create } from 'zustand';
import { useProjectStore } from './useProjectStore';
import { EXPECTED_RUNTIME, restartBackend, sharkBackend, sharkWorkspace, sharkWorkflows, type AgentTask, type ChangePreview, type ImpactReport, type ProviderStatus, type SlashCommand, type TaskEvent } from '../lib/sharkBackend';

export interface RunOptions { provider: string; model: string; apiKey?: string; effort?: string; mode?: string; skills?: string[]; customSkills?: string[]; group?: string; workflow?: boolean }
interface AgentWorkspace {
  tasks: AgentTask[]; activeId: string; events: TaskEvent[]; cursor: number;
  impact: ImpactReport | null; proposal: ChangePreview | null;
  providers: ProviderStatus[]; commands: SlashCommand[]; catalog: Record<string, { id: string; label: string }[]>; loadModels(provider: string): Promise<void>; error: string; busy: boolean; connected: boolean;
  connect(): Promise<void>; select(id: string): Promise<void>; fresh(): void;
  run(goal: string, options: RunOptions): Promise<boolean>;
  spawn(goal: string, options: RunOptions): Promise<void>; refreshTasks(): Promise<void>;
  poll(): Promise<void>; review(): Promise<void>; apply(): Promise<void>; cancel(): Promise<void>; clearError(): void;
}
const message = (e: unknown) => e instanceof Error ? e.message : String(e);
let generation = 0;

export const useAgentWorkspace = create<AgentWorkspace>((set, get) => ({
  tasks: [], activeId: '', events: [], cursor: 0, impact: null, proposal: null, providers: [], commands: [], catalog: {},
  loadModels: async provider => {
    if (get().catalog[provider] || !useProjectStore.getState().root || useProjectStore.getState().kind !== 'native') return;
    try { const r = await sharkWorkspace.models(provider); set(s => ({ catalog: { ...s.catalog, [provider]: r.models } })); } catch { /* keep static suggestions */ }
  },
  error: '', busy: false, connected: false,
  connect: async () => {
    const token = ++generation;
    set({ connected: false, tasks: [], activeId: '', events: [], cursor: 0, proposal: null, impact: null, error: '' });
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
    set({ activeId: id, events: [], cursor: 0, proposal: null, impact: null, error: '' });
    await get().poll(); await get().review();
  },
  fresh: () => set({ activeId: '', events: [], cursor: 0, proposal: null, impact: null, error: '' }),
  run: async (goal, { provider, model, apiKey, effort, mode, skills, customSkills, group, workflow }) => {
    set({ busy: true, error: '' });
    try {
      const created = workflow ? await sharkWorkflows.create(goal, { provider, model, ...(effort ? { effort } : {}), ...(mode ? { mode } : {}), skills: skills ?? [], custom_skills: customSkills ?? [], ...(group ? { group } : {}) }) : null;
      const task = created?.task ?? await sharkWorkspace.createTask(goal);
      set(s => ({ tasks: [task, ...s.tasks], activeId: task.id, events: [], cursor: 0, proposal: null, impact: null }));
      if (created) await sharkWorkflows.start(created.workflow.id, apiKey);
      else await sharkWorkspace.start(task.id, { provider, model, ...(apiKey ? { api_key: apiKey } : {}), ...(effort ? { effort } : {}), mode, skills, custom_skills: customSkills, ...(group ? { group } : {}) });
      await get().poll();
      return true;
    } catch (e) { set({ error: message(e) }); return false; }
    finally { set({ busy: false }); }
  },
  spawn: async (goal, o) => {
    try {
      const created = o.workflow ? await sharkWorkflows.create(goal, { provider: o.provider, model: o.model, ...(o.effort ? { effort: o.effort } : {}), ...(o.mode ? { mode: o.mode } : {}), skills: o.skills ?? [], custom_skills: o.customSkills ?? [], ...(o.group ? { group: o.group } : {}) }) : null;
      const task = created?.task ?? await sharkWorkspace.createTask(goal);
      set(s => ({ tasks: [task, ...s.tasks] }));
      if (created) await sharkWorkflows.start(created.workflow.id, o.apiKey);
      else await sharkWorkspace.start(task.id, { provider: o.provider, model: o.model, ...(o.apiKey ? { api_key: o.apiKey } : {}), ...(o.effort ? { effort: o.effort } : {}), mode: o.mode, skills: o.skills, custom_skills: o.customSkills, group: o.group });
    } catch (e) { set({ error: message(e) }); }
  },
  refreshTasks: async () => {
    try { const r = await sharkWorkspace.tasks(); set({ tasks: r.tasks }); } catch { /* backend offline: keep the last known list */ }
  },
  poll: async () => {
    const id = get().activeId; if (!id) return;
    try {
      const task = await sharkWorkspace.task(id);
      // Drain everything new so streamed text never lags behind the agent.
      for (let i = 0; i < 20; i++) {
        const page = await sharkWorkspace.events(id, get().cursor);
        if (get().activeId !== id) return;
        set(s => ({ events: [...s.events, ...page.events.filter(e => e.sequence > (s.events.at(-1)?.sequence ?? 0))], cursor: page.next_cursor }));
        if (!page.has_more) break;
      }
      set(s => ({ tasks: s.tasks.map(t => t.id === id ? task : t) }));
      if (task.proposal_id && !get().proposal) await get().review();
    } catch (e) { if (get().activeId === id) set({ error: message(e) }); }
  },
  review: async () => {
    const id = get().activeId; if (!id) return;
    try {
      const task = await sharkWorkspace.task(id); if (!task.proposal_id) return;
      const result = await sharkWorkspace.analyze(task.proposal_id);
      if (get().activeId === id) set({ proposal: result.proposal, impact: result.impact });
    } catch (e) { if (get().activeId === id) set({ error: message(e) }); }
  },
  apply: async () => {
    const id = get().activeId; if (!id) return;
    set({ busy: true, error: '' });
    try {
      const paths = get().proposal?.files.map(f => f.path) || [];
      if (useProjectStore.getState().tabs.some(t => paths.includes(t.path) && t.content !== t.saved))
        throw new Error('Save or discard your edits in the affected files first, then apply again.');
      const result = await sharkWorkspace.apply(id);
      set(s => ({ proposal: result.proposal, tasks: s.tasks.map(t => t.id === id ? result.task : t) }));
      await get().poll();
      await useProjectStore.getState().refreshFromDisk(paths);
    } catch (e) { set({ error: message(e) }); }
    finally { set({ busy: false }); }
  },
  cancel: async () => { try { await sharkWorkspace.cancel(get().activeId); await get().poll(); } catch (e) { set({ error: message(e) }); } },
  clearError: () => set({ error: '' }),
}));
