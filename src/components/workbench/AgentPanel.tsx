import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import {
  AlertCircle, ArrowRight, ArrowUp, AtSign, BookOpen, Bot, Bug, Check, ChevronDown, ChevronRight, CircleAlert, CornerDownRight, FileCode2, FilePen, FilePlus2,
  FileSearch, FlaskConical, Folder, FolderTree, GitCompareArrows, Globe, Hammer, History, Info, ListChecks, Map as MapIcon, Network, Plus, RefreshCw, Search,
  Layers, RotateCw, Settings2, ShieldAlert, Sparkles, Square, SquareTerminal, Wand2, Wrench, X, Zap,
} from 'lucide-react';
import { useAgentWorkspace } from '../../stores/useAgentWorkspace';
import { useProjectStore } from '../../stores/useProjectStore';
import { useProfiles } from '../../stores/useProfiles';
import { API_ORDER, BUILTIN_SKILLS, CLI_ORDER, EFFORTS, MODES, PROVIDERS, useSettings, type Effort, type ModeId, type ProviderId } from '../../stores/useSettings';
import { lineDiff, readArtifact, type DiffLine } from '../../lib/artifacts';
import { useUi } from '../../stores/useUi';
import type { ProviderStatus, TaskEvent } from '../../lib/sharkBackend';
import { Markdown } from './Markdown';
import { Select } from './NativeUi';
import { WorkflowControls } from './WorkflowControls';
import { changeKind, FileIcon, Popover, SharkMark } from './primitives';
import { detectTasks, defaultTask } from './tasks';
import { askAgent } from './BottomPanel';
import { pluginPrompt } from './plugins';

const STATUS: Record<string, string> = { created: 'Not started', running: 'Working', review: 'Ready to review', applied: 'Applied', completed: 'Done', cancelled: 'Stopped', interrupted: 'Interrupted', failed: 'Failed', paused: 'Paused', waiting_human: 'Needs your answer', blocked: 'Needs attention' };

export function readiness(id: ProviderId, native: boolean, statuses: ProviderStatus[], keys: Partial<Record<ProviderId, string>>) {
  if (!native) return { ready: false, label: 'Desktop app', tone: '' };
  const status = statuses.find(p => p.id === id);
  if (PROVIDERS[id].kind === 'cli') {
    if (!status) return { ready: false, label: 'Checking…', tone: '' };
    return status.available ? { ready: true, label: 'Ready', tone: 'ok' } : { ready: false, label: 'Not installed', tone: 'err' };
  }
  if (keys[id]) return { ready: true, label: 'Key added', tone: 'ok' };
  if (status?.env_configured) return { ready: true, label: 'From environment', tone: 'ok' };
  return { ready: false, label: 'Needs key', tone: 'warn' };
}

async function runDefaultTask(group: 'build' | 'test') {
  const p = useProjectStore.getState();
  const t = defaultTask(await detectTasks(p.entries, p.readText), group);
  if (t) { const { runTask } = await import('./Sidebar'); await runTask(t); }
  else useSettings.getState().set({ sidebarOpen: true, sidebarView: 'run' });
}

/* Goal encoding: follow-up context and attachments travel inside the task goal. */
const CONTEXT = /^\[context\]\n([\s\S]*?)\n\[\/context\]\n\n/;
const ATTACHED = /\n\n(?:Open file|Attached files): (.+)$/;
export function parseGoal(goal: string) {
  let text = goal, continues = '', files: string[] = [];
  const c = CONTEXT.exec(text); if (c) { continues = /Previous request: (.*)/.exec(c[1])?.[1] ?? ''; text = text.slice(c[0].length); }
  const a = ATTACHED.exec(text); if (a) { files = a[1].split(', '); text = text.slice(0, a.index); }
  return { text, continues, files };
}

type Step = { id: string; name: string; target: string; done: boolean; error: boolean; children?: Step[] };
type Block =
  | { type: 'thinking'; text: string; start: number; end: number; done: boolean }
  | { type: 'steps'; steps: Step[] }
  | { type: 'text'; text: string }
  | { type: 'error'; message: string; category: string }
  | { type: 'notice'; text: string }
  | { type: 'lifecycle'; kind: 'compaction' | 'retry'; message: string; tokensBefore: number | null; at: number };
export type Usage = {
  input: number; output: number; cached: number; cost?: number | null; context_window?: number | null;
  /** Prompt size of the latest model call (the live context) and how much of it came from the prompt cache. */
  context?: number; context_cached?: number; compactions?: number; retries?: number;
};
// Context windows by engine when the engine does not report one (Claude reports its own).
const WINDOWS: Partial<Record<string, number>> = { 'claude-code': 200_000, anthropic: 200_000, antigravity: 1_048_576, gemini: 1_048_576, codex: 400_000 };
export const kTokens = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n);
/** Live context fill (0-1, null when unknown) and prompt-cache reuse on the latest call. */
export function contextState(usage: Usage | null, engine?: string | null) {
  if (!usage) return null;
  const window = usage.context_window || WINDOWS[engine ?? ''] || null;
  const live = usage.context ?? null;
  const fill = window && live != null ? Math.min(1, live / window) : null;
  const cacheRate = live ? (usage.context_cached ?? 0) / live : usage.input + usage.cached > 0 ? usage.cached / (usage.input + usage.cached) : null;
  const cache = cacheRate == null ? null : cacheRate >= 0.6 ? 'hot' : cacheRate >= 0.2 ? 'warm' : (live ?? usage.input) > 8000 ? 'cold' : null;
  return { window, live, fill, cacheRate, cache } as const;
}
export const MODE_ICONS: Record<ModeId, typeof Wrench> = { builder: Hammer, debugger: Bug, review: ShieldAlert, planner: ListChecks, explain: BookOpen, tests: FlaskConical, refactor: Wand2 };

function toBlocks(events: TaskEvent[], running: boolean) {
  const blocks: Block[] = [];
  let streaming = '';
  let totals: Usage | null = null;
  let live: { context: number; context_cached: number } | null = null;
  let compactions = 0, retries = 0;
  const closeThinking = () => { const last = blocks.at(-1); if (last?.type === 'thinking') last.done = true; };
  for (const e of events) {
    const last = blocks.at(-1);
    if (e.kind === 'thinking_delta' || e.kind === 'thinking') {
      const text = String(e.data.text ?? '');
      if (last?.type === 'thinking' && !last.done) { last.text = e.kind === 'thinking' ? text : last.text + text; last.end = e.timestamp; if (e.kind === 'thinking') last.done = true; }
      else blocks.push({ type: 'thinking', text, start: e.timestamp, end: e.timestamp, done: e.kind === 'thinking' });
      continue;
    }
    if (e.kind === 'text_delta') { closeThinking(); streaming += String(e.data.text ?? ''); continue; }
    if (e.kind === 'tool_call') {
      closeThinking(); streaming = '';
      const step: Step = { id: String(e.data.call_id ?? e.sequence), name: String(e.data.name ?? 'tool'), target: String(e.data.target ?? ''), done: false, error: false };
      // A subagent's own calls nest under the step that started it.
      const owner = e.data.parent ? blocks.flatMap(b => b.type === 'steps' ? b.steps : []).find(st => st.id === String(e.data.parent)) : undefined;
      if (owner) { (owner.children ??= []).push(step); continue; }
      if (last?.type === 'steps') last.steps.push(step); else blocks.push({ type: 'steps', steps: [step] });
    } else if (e.kind === 'tool_result') {
      for (const b of blocks) if (b.type === 'steps') for (const st of b.steps) for (const x of [st, ...(st.children ?? [])]) if (x.id === String(e.data.call_id)) { x.done = true; x.error = !!e.data.error; }
    } else if (e.kind === 'text') { closeThinking(); streaming = ''; blocks.push({ type: 'text', text: String(e.data.text ?? '') }); }
    else if (e.kind === 'error') { closeThinking(); blocks.push({ type: 'error', message: String(e.data.message ?? 'Shark reported an error.'), category: String(e.data.category ?? 'other') }); }
    else if (e.kind === 'notice' && (e.data.kind === 'compaction' || e.data.kind === 'retry')) {
      if (e.data.kind === 'compaction') compactions++; else retries++;
      // Consecutive retries collapse into one line.
      if (e.data.kind === 'retry' && last?.type === 'lifecycle' && last.kind === 'retry') last.at = e.timestamp;
      else blocks.push({ type: 'lifecycle', kind: e.data.kind, message: String(e.data.message ?? ''), tokensBefore: typeof e.data.tokens_before === 'number' ? e.data.tokens_before : null, at: e.timestamp });
    }
    else if (e.kind === 'notice') blocks.push({ type: 'notice', text: String(e.data.text ?? '') });
    else if (e.kind === 'usage') {
      const d = e.data as unknown as Usage;
      if (d.context) live = { context: d.context, context_cached: d.context_cached ?? 0 };
      if (d.input || d.output) totals = Object.assign({}, totals as Usage | null, d);
    }
  }
  // A step is finished once anything comes after it, or once the run ends.
  let later = !!streaming;
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i];
    if (b.type === 'steps') b.steps.forEach((st, k) => { if (!running || later || k < b.steps.length - 1) { st.done = true; st.children?.forEach(c => { c.done = true; }); } });
    if (b.type === 'thinking' && (!running || later)) b.done = true;
    later = true;
  }
  const usage: Usage | null = totals || live ? { input: 0, output: 0, cached: 0, ...totals, ...(live ?? {}), compactions, retries } : null;
  return { blocks, streaming: running ? streaming : '', usage };
}

function Lifecycle({ block }: { block: Extract<Block, { type: 'lifecycle' }> }) {
  if (block.kind === 'retry') return <p className="notice warn lifecycle"><RotateCw size={13} className="spin-slow" />Provider busy, retrying automatically.</p>;
  return <div className="compaction" role="note">
    <span className="compaction-rule" aria-hidden="true" />
    <span className="compaction-label"><Layers size={12} />Context compacted{block.tokensBefore ? ` at ${kTokens(block.tokensBefore)} tokens` : ''}</span>
    <span className="compaction-rule" aria-hidden="true" />
    <p className="fine">Older turns were summarised to make room. If Shark seems to forget an early requirement, restate it.</p>
  </div>;
}

/** 850ms, 42s, 3m 07s, 1h 02m */
function elapsed(seconds: number) {
  const t = Math.max(0, seconds);
  if (t < 1) return `${Math.round(t * 1000)}ms`;
  if (t < 60) return `${Math.floor(t)}s`;
  const m = Math.floor(t / 60), sec = Math.floor(t % 60);
  if (m < 60) return `${m}m ${String(sec).padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
}

function describe(name: string): { icon: typeof Wrench; verb: string } {
  const n = name.toLowerCase();
  if (n.includes('isolated')) return { icon: FolderTree, verb: 'Prepared workspace' };
  if (n === 'shark_graph') return { icon: Network, verb: 'Queried code graph' };
  if (n.includes('check_page') || n.includes('check page')) return { icon: Globe, verb: 'Checked page' };
  if (n === 'shark_outline') return { icon: ListChecks, verb: 'Outlined' };
  if (n === 'shark_git') return { icon: GitCompareArrows, verb: 'Checked git' };
  if (n.includes('code graph')) return { icon: Network, verb: 'Explored code graph' };
  if (n === 'task' || n === 'agent' || n.includes('subagent') || n.includes('spawn') || n.includes('delegate')) return { icon: Bot, verb: 'Subagent' };
  if (n.includes('browser') || n.includes('web') || n.includes('url')) return { icon: Globe, verb: 'Browsed' };
  if (n.includes('read') || n === 'view' || n.includes('view_file')) return { icon: FileCode2, verb: 'Read' };
  if (n.includes('explore') || n.includes('list')) return { icon: MapIcon, verb: 'Explored' };
  if (n.includes('impact')) return { icon: GitCompareArrows, verb: 'Checked impact' };
  if (n.includes('search') || n.includes('grep') || n.includes('glob') || n.includes('find')) return { icon: FileSearch, verb: 'Searched' };
  if (n.includes('propose')) return { icon: GitCompareArrows, verb: 'Proposed changes' };
  if (n.includes('create') || (n.includes('write') && !n.includes('rewrite'))) return { icon: FilePlus2, verb: 'Wrote' };
  if (n.includes('edit') || n.includes('replace') || n.includes('update') || n.includes('delete') || n.includes('patch')) return { icon: FilePen, verb: 'Edited' };
  if (n.includes('shell') || n.includes('bash') || n.includes('command') || n.includes('terminal')) return { icon: SquareTerminal, verb: 'Ran' };
  return { icon: Wrench, verb: name.replace(/_/g, ' ') };
}

function shortTarget(target: string, root: string) {
  const t = target.startsWith(root + '/') ? target.slice(root.length + 1) : target;
  return t.replace(/^\/tmp\/shark-cli-[^/]+\/[^/]+\//, '');
}

function Thinking({ block }: { block: Extract<Block, { type: 'thinking' }> }) {
  const seconds = Math.max(1, Math.round(block.end - block.start));
  return <details className="thought">
    <summary>
      <ChevronRight size={13} className="chev" />
      {block.done ? <span>Thought for {seconds}s</span> : <span className="thinking-label">Thinking<span className="dots"><i /><i /><i /></span></span>}
    </summary>
    {block.text && <div className="thought-body">{block.text}</div>}
  </details>;
}

function Steps({ steps, root }: { steps: Step[]; root: string }) {
  return <ol className="timeline">
    {steps.map((s, i) => {
      const d = describe(s.name), Icon = d.icon, target = shortTarget(s.target, root);
      return <li key={s.id + i} className={`${s.done ? (s.error ? 'is-error' : 'is-done') : 'is-active'} ${d.verb === 'Subagent' ? 'is-subagent' : ''}`}>
        <span className="step-state" aria-hidden="true">{s.done ? (s.error ? <X size={11} /> : <Check size={11} />) : <span className="spinner" />}</span>
        <Icon size={14} className="step-icon" />
        <span className="what">{d.verb}</span>
        {target && <span className="target" title={s.target}>{target}</span>}
        {s.children?.length ? <ol className="timeline sub-timeline" aria-label="Subagent steps">
          {s.children.slice(-12).map((c, k) => { const cd = describe(c.name), CIcon = cd.icon, ct = shortTarget(c.target, root);
            return <li key={c.id + k} className={c.done ? (c.error ? 'is-error' : 'is-done') : 'is-active'}>
              <span className="step-state" aria-hidden="true">{c.done ? (c.error ? <X size={10} /> : <Check size={10} />) : <span className="spinner" />}</span>
              <CIcon size={13} className="step-icon" /><span className="what">{cd.verb}</span>{ct && <span className="target" title={c.target}>{ct}</span>}
            </li>; })}
          {s.children.length > 12 && <li className="fine">+{s.children.length - 12} earlier steps</li>}
        </ol> : null}
      </li>;
    })}
  </ol>;
}

const ERROR_TITLES: Record<string, string> = { quota: 'Quota used up', rate_limit: 'Rate limited', auth: 'Not signed in', context: 'Context window full', network: 'Connection problem', other: 'Something went wrong' };
function ErrorCallout({ block, onRetry, onNewChat }: { block: Extract<Block, { type: 'error' }>; onRetry(): void; onNewChat(): void }) {
  const open = (section: 'agents') => useUi.getState().open('settings', section);
  return <div className="callout error" role="alert">
    <AlertCircle size={15} />
    <div className="grow">
      <strong>{ERROR_TITLES[block.category] ?? ERROR_TITLES.other}</strong>
      <span>{block.message}</span>
      <div className="actions">
        {(block.category === 'rate_limit' || block.category === 'network' || block.category === 'other') && <button className="btn sm" onClick={onRetry}><RefreshCw size={12} />Retry</button>}
        {(block.category === 'quota' || block.category === 'rate_limit' || block.category === 'auth') && <button className="btn sm" onClick={() => open('agents')}>Switch engine</button>}
        {block.category === 'context' && <button className="btn sm" onClick={onNewChat}>New chat with summary</button>}
      </div>
    </div>
  </div>;
}

function ContextMeter({ usage, engine }: { usage: Usage | null; engine?: string | null }) {
  const state = contextState(usage, engine);
  if (!usage || !state) return null;
  const { fill, window, live, cache, cacheRate } = state;
  const tone = fill == null ? '' : fill > 0.9 ? 'err' : fill > 0.75 ? 'warn' : '';
  const lines = [
    live != null ? `Context: ${kTokens(live)}${window ? ` of ${kTokens(window)} (${Math.round((fill ?? 0) * 100)}%)` : ''}` : window ? `Context window: ${kTokens(window)}` : 'Context size not reported by this engine',
    cacheRate != null ? `Prompt cache: ${Math.round(cacheRate * 100)}% of the latest prompt reused${cache === 'hot' ? ' (fast and cheap)' : cache === 'cold' ? ' (first call, or the cache expired)' : ''}` : '',
    usage.input || usage.output ? `This run: ${kTokens(usage.input)} in, ${kTokens(usage.output)} out${usage.cached ? `, ${kTokens(usage.cached)} cached` : ''}` : '',
    usage.cost ? `Cost: $${usage.cost.toFixed(3)}` : '',
    usage.compactions ? `Compacted ${usage.compactions}x: early details may be summarised` : '',
  ].filter(Boolean).join('\n');
  return <span className="ctx-group" title={lines}>
    {usage.compactions ? <span className="ctx-badge compact"><Layers size={11} />{usage.compactions > 1 ? usage.compactions : ''}<span className="sr-only">context compacted</span></span> : null}
    {cache && cache !== 'warm' && <span className={`ctx-badge cache-${cache}`}><Zap size={11} />{cache === 'hot' ? 'Cached' : 'Cold'}</span>}
    <span className={`ctx-meter ${tone}`}>
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="8" className="track" /><circle cx="10" cy="10" r="8" className="fill" style={{ strokeDasharray: `${(fill ?? 0) * 50.27} 50.27` }} /></svg>
      <span className="sr-only">{fill != null ? `${Math.round(fill * 100)}% of context used` : 'context size unknown'}</span>
    </span>
  </span>;
}

type MenuItem = { key: string; section: string; label: string; detail?: string; right?: string; active?: boolean; pick(): void };

export function AgentPanel() {
  const agent = useAgentWorkspace();
  const project = useProjectStore();
  const s = useSettings();
  const profile = useProfiles(p => p.profiles.find(x => x.id === p.active));
  const composerFocus = useUi(u => u.composerFocus);
  const draft = useUi(u => u.draft);
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState<string[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [menu, setMenu] = useState<null | 'model' | 'attach' | 'mode'>(null);
  const [autonomous, setAutonomous] = useState(true);
  const [parallel, setParallel] = useState<ProviderId[]>([]);
  const [fileQuery, setFileQuery] = useState('');
  const [menuIndex, setMenuIndex] = useState(0);
  const [now, setNow] = useState(Date.now());
  const textarea = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  const native = project.kind === 'native';
  const task = agent.tasks.find(t => t.id === agent.activeId);
  const running = task?.status === 'running';
  const ready = readiness(s.provider, native, agent.providers, s.keys);
  const model = s.models[s.provider];
  const effort: Effort = s.efforts[s.provider] ?? '';
  const catalog = agent.catalog[s.provider] ?? PROVIDERS[s.provider].models.filter(Boolean).map(id => ({ id, label: id }));
  const modelLabel = catalog.find(m => m.id === model)?.label ?? (model || `${PROVIDERS[s.provider].label} · Auto`);
  const { blocks, streaming, usage } = useMemo(() => toBlocks(agent.events, !!running), [agent.events, running]);
  const mode = MODES.find(m => m.id === s.mode) ?? MODES[0];
  const ModeIcon = MODE_ICONS[mode.id];
  const activeSkills = [...BUILTIN_SKILLS.filter(k => s.skills.includes(k.id)).map(k => k.label), ...s.customSkills.filter(c => s.activeCustomSkills.includes(c.id)).map(c => c.name)];
  const siblings = task?.group ? agent.tasks.filter(t => t.group === task.group).sort((a, b) => a.created_at - b.created_at) : [];
  const anyRunning = agent.tasks.some(t => t.status === 'running');
  const goal = task ? parseGoal(task.goal) : null;
  const startedAt = agent.events.find(e => e.kind === 'started')?.timestamp;
  const finishedAt = [...agent.events].reverse().find(e => ['completed', 'failed', 'cancelled', 'review', 'proposal'].includes(e.kind))?.timestamp;
  const empty = !task && pending === null;

  useEffect(() => {
    if (!task || !native || !running) return;
    let disposed = false, timer: ReturnType<typeof setTimeout>;
    const tick = async () => { if (disposed) return; await useAgentWorkspace.getState().poll(); setNow(Date.now()); if (!disposed) timer = setTimeout(tick, 500); };
    timer = setTimeout(tick, 300);
    return () => { disposed = true; clearTimeout(timer); };
  }, [task?.id, running, native]);
  useEffect(() => {
    if (!native || !anyRunning) return;
    const id = setInterval(() => void useAgentWorkspace.getState().refreshTasks(), 2000);
    return () => clearInterval(id);
  }, [native, anyRunning]);
  useEffect(() => { if (native && agent.connected) void agent.loadModels(s.provider); }, [s.provider, native, agent.connected]); // eslint-disable-line react-hooks/exhaustive-deps

  useLayoutEffect(() => { const el = scroller.current; if (el && pinned.current) el.scrollTop = el.scrollHeight; }, [agent.events, agent.proposal, task?.status, pending]);
  useEffect(() => { pinned.current = true; }, [agent.activeId]);
  useEffect(() => { if (composerFocus) textarea.current?.focus(); }, [composerFocus]);
  useEffect(() => { if (draft) { setInput(draft.text); textarea.current?.focus(); } }, [draft]);
  useLayoutEffect(() => { const el = textarea.current; if (!el) return; el.style.height = 'auto'; el.style.height = `${el.scrollHeight}px`; }, [input, empty]);

  const setModel = (id: string) => s.set({ models: { ...s.models, [s.provider]: id } });
  const setEffort = (id: Effort) => s.set({ efforts: { ...s.efforts, [s.provider]: id } });
  const attach = (path: string) => setAttachments(a => a.includes(path) ? a : [...a, path]);

  /* Slash menu: engine controls, the engine's own commands, then Shark actions. */
  const slashItems = useMemo((): MenuItem[] => {
    const done = () => { setInput(''); textarea.current?.focus(); };
    const sub = /^\/(model|effort|engine)\s+(.*)$/.exec(input);
    if (sub) {
      const q = sub[2].toLowerCase();
      if (sub[1] === 'model') return [{ id: '', label: 'Auto' }, ...catalog].filter(m => !q || m.label.toLowerCase().includes(q) || m.id.toLowerCase().includes(q))
        .map(m => ({ key: m.id || 'default', section: `${PROVIDERS[s.provider].label} models`, label: m.label, detail: m.id, active: m.id === model, pick: () => { setModel(m.id); done(); } }));
      if (sub[1] === 'effort') return EFFORTS.filter(e => !q || e.label.toLowerCase().includes(q)).map(e => ({ key: e.id || 'default', section: 'Thinking effort', label: e.label, active: e.id === effort, pick: () => { setEffort(e.id); done(); } }));
      return [...CLI_ORDER, ...API_ORDER].filter(id => !q || PROVIDERS[id].label.toLowerCase().includes(q)).map(id => {
        const r = readiness(id, native, agent.providers, s.keys);
        return { key: id, section: 'Engine', label: PROVIDERS[id].label, detail: PROVIDERS[id].kind === 'cli' ? 'CLI' : 'API key', right: r.label, active: id === s.provider, pick: () => { s.set({ provider: id }); done(); } };
      });
    }
    const m = /^\/(\S*)$/.exec(input); if (!m) return [];
    const q = m[1].toLowerCase();
    const items: MenuItem[] = [
      { key: 'model', section: 'Engine', label: '/model', detail: `Change model · ${modelLabel}`, pick: () => setInput('/model ') },
      { key: 'effort', section: 'Engine', label: '/effort', detail: `Thinking effort · ${EFFORTS.find(e => e.id === effort)?.label}`, pick: () => setInput('/effort ') },
      ...MODES.map(m => ({ key: 'mode:' + m.id, section: 'Mode', label: `/${m.id}`, detail: `${m.label}: ${m.hint}`, active: m.id === s.mode, pick: () => { s.set({ mode: m.id }); setInput(''); } })),
      { key: 'engine', section: 'Engine', label: '/engine', detail: `Switch engine · ${PROVIDERS[s.provider].label}`, pick: () => setInput('/engine ') },
      ...agent.commands.filter(c => c.provider === s.provider).map(c => ({ key: 'c:' + c.name, section: `${PROVIDERS[s.provider].label} commands`, label: `/${c.name}`, detail: c.description || (c.scope === 'project' ? 'Project command' : 'Your command'), right: c.argument_hint, pick: () => setInput(`/${c.name} `) })),
      { key: 'new', section: 'Shark', label: '/new', detail: 'Start a new chat', pick: () => { agent.fresh(); setInput(''); } },
      { key: 'review', section: 'Shark', label: '/review', detail: 'Open the current review', pick: () => { useUi.getState().set({ editorView: 'review' }); setInput(''); } },
      { key: 'apply', section: 'Shark', label: '/apply', detail: 'Apply the reviewed changes', pick: () => { void agent.apply(); setInput(''); } },
      { key: 'build', section: 'Shark', label: '/build', detail: 'Run the build task', pick: () => { void runDefaultTask('build'); setInput(''); } },
      { key: 'test', section: 'Shark', label: '/test', detail: 'Run the test task', pick: () => { void runDefaultTask('test'); setInput(''); } },
      { key: 'fix', section: 'Shark', label: '/fix', detail: 'Fix current problems', pick: () => setInput(`Fix these problems:\n${useUi.getState().problems.slice(0, 30).map(p => `- ${p.path}:${p.line} ${p.message}`).join('\n') || '(none reported in open files)'}`) },
      { key: 'plugin', section: 'Shark', label: '/plugin', detail: 'Create a Shark plugin', right: '<idea>', pick: () => setInput('/plugin ') },
    ];
    return items.filter(i => i.label.slice(1).toLowerCase().startsWith(q));
  }, [input, catalog, model, effort, s, agent, native, modelLabel]); // eslint-disable-line react-hooks/exhaustive-deps

  const slashKey = `${input.split(' ')[0]}:${slashItems.length}`;
  useEffect(() => { setMenuIndex(0); }, [slashKey]);

  async function send() {
    let text = input.trim();
    if (!text || running || agent.busy) return;
    setNote('');
    const plugin = /^\/plugin\s+([\s\S]+)$/.exec(text);
    if (plugin) { s.set({ sidebarOpen: true, sidebarView: 'plugins' }); askAgent(pluginPrompt(plugin[1])); return; }
    if (!native) { setNote('Shark runs in the desktop app. Start it with npm run tauri dev.'); return; }
    if (!agent.connected) { setNote('The local backend is not connected yet.'); return; }
    if (!ready.ready) { useUi.getState().open('settings', 'agents'); return; }
    const command = /^\/(\S+)/.exec(text);
    const custom = command ? agent.commands.find(c => c.provider === s.provider && c.name === command[1]) : undefined;
    if (custom?.kind === 'prompt' && custom.body) text = custom.body.replace(/\$ARGUMENTS/g, text.slice(command![0].length).trim());
    // Engines that expand their own slash commands receive them exactly as typed.
    const passThrough = !!command && custom?.kind !== 'prompt' && (custom?.kind === 'native' || s.provider === 'antigravity' || s.provider === 'claude-code');
    let goalText = text;
    if (!passThrough) {
      const files = [...attachments, ...(s.attachActiveFile && project.activePath && !attachments.includes(project.activePath) ? [project.activePath] : [])];
      if (files.length) goalText += `\n\nAttached files: ${files.join(', ')}`;
      if (task && task.status !== 'created') {
        const previous = task.summary || [...blocks].reverse().find(b => b.type === 'text')?.text || STATUS[task.status];
        goalText = `[context]\nPrevious request: ${parseGoal(task.goal).text.split('\n')[0].slice(0, 300)}\nPrevious result: ${String(previous).slice(0, 1500)}\n[/context]\n\n${goalText}`;
      }
    }
    const start = () => flushSync(() => { setPending(goalText); setInput(''); setAttachments([]); });
    const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
    if (empty && doc.startViewTransition && !s.reduceMotion) doc.startViewTransition(start); else start();
    pinned.current = true;
    const shared = { workflow: autonomous && !mode.readOnly, mode: s.mode, skills: s.skills, customSkills: s.customSkills.filter(c => s.activeCustomSkills.includes(c.id)).map(c => c.text) };
    const group = parallel.length ? Math.random().toString(36).slice(2, 10) : undefined;
    const ok = await agent.run(goalText, { provider: s.provider, model, apiKey: s.keys[s.provider], effort, ...shared, group });
    if (ok && group) for (const id of parallel.filter(p => p !== s.provider && readiness(p, native, agent.providers, s.keys).ready))
      await agent.spawn(goalText, { provider: id, model: s.models[id], apiKey: s.keys[id], effort: s.efforts[id] ?? '', ...shared, group });
    if (!ok) setInput(text);
    setPending(null);
  }

  const greeting = profile && profile.name !== 'Default' ? `Hello, ${profile.name}.` : 'What should we build?';
  const suggestions = [
    { icon: MapIcon, text: 'Explain how this project is structured' },
    { icon: Bug, text: project.activePath ? `Find bugs in ${project.activePath.split('/').pop()}` : 'Find likely bugs in this project' },
    { icon: FlaskConical, text: project.activePath ? `Write tests for ${project.activePath.split('/').pop()}` : 'Suggest tests for the riskiest code' },
  ];
  const error = agent.error || project.error;
  const fileMatches = menu === 'attach' ? project.entries.filter(e => !e.directory && (!fileQuery || e.path.toLowerCase().includes(fileQuery.toLowerCase()))).slice(0, 8) : [];

  const composer = <div className="composer-wrap">
    {slashItems.length > 0 && <div className="popover slash-menu" role="listbox" aria-label="Commands">
      {slashItems.map((c, i) => <div key={c.key}>
        {(i === 0 || slashItems[i - 1].section !== c.section) && <div className="group label">{c.section}</div>}
        <button role="option" aria-selected={i === menuIndex} className={`menu-item ${i === menuIndex ? 'focused' : ''}`} onMouseMove={() => setMenuIndex(i)} onClick={() => { c.pick(); textarea.current?.focus(); }}>
          <span className="slash-name">{c.label}</span>
          <span className="text"><small>{c.detail}</small></span>
          {c.right && <span className="state">{c.right}</span>}
          {c.active && <Check size={14} />}
        </button>
      </div>)}
    </div>}
    <form className="composer" style={{ viewTransitionName: 'composer' } as React.CSSProperties} onSubmit={e => { e.preventDefault(); void send(); }}>
      <div className="composer-context">
        <span className="ctx-chip folder" title={project.root}><Folder size={12} />{project.name}</span>
        {attachments.map(p => <span key={p} className="ctx-chip" title={p}><FileIcon path={p} size={12} />{p.split('/').pop()}<button type="button" aria-label={`Remove ${p}`} onClick={() => setAttachments(a => a.filter(x => x !== p))}><X size={11} /></button></span>)}
        {project.activePath && !attachments.includes(project.activePath) && <button type="button" className={`ctx-chip toggle ${s.attachActiveFile ? 'on' : ''}`} aria-pressed={s.attachActiveFile}
          title={s.attachActiveFile ? 'Shared with Shark. Click to stop sharing' : 'Share the open file with Shark'} onClick={() => s.set({ attachActiveFile: !s.attachActiveFile })}>
          <FileIcon path={project.activePath} size={12} />{project.activePath.split('/').pop()}
        </button>}
      </div>
      <label htmlFor="composer" className="sr-only">Message Shark</label>
      <textarea id="composer" ref={textarea} rows={empty ? 2 : 1} value={input} onChange={e => setInput(e.target.value)} autoFocus
        placeholder={task && task.status !== 'created' ? 'Follow up…' : 'Ask anything, @ to add files, / for commands'}
        onKeyDown={e => {
          if (slashItems.length) {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); setMenuIndex(i => (i + (e.key === 'ArrowDown' ? 1 : -1) + slashItems.length) % slashItems.length); return; }
            if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) { e.preventDefault(); slashItems[Math.min(menuIndex, slashItems.length - 1)].pick(); return; }
            if (e.key === 'Escape') { e.preventDefault(); setInput(''); return; }
          }
          if (e.key === '@' && !input.trim()) { e.preventDefault(); setFileQuery(''); setMenu('attach'); return; }
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); }
        }} />
      <div className="composer-bar">
        <div style={{ position: 'relative' }}>
          <button type="button" className="icon-btn round" data-popover-anchor aria-label="Add context" title="Add files and context" aria-expanded={menu === 'attach'} onClick={() => { setFileQuery(''); setMenu(m => m === 'attach' ? null : 'attach'); }}><Plus size={16} /></button>
          <Popover open={menu === 'attach'} onClose={() => setMenu(null)} className="attach-pop" style={{ left: 0, bottom: 'calc(100% + 8px)' }}>
            <div className="model-field"><input className="field" autoFocus placeholder="Add a file…" value={fileQuery} onChange={e => setFileQuery(e.target.value)} aria-label="Find a file to attach"
              onKeyDown={e => { if (e.key === 'Enter' && fileMatches[0]) { attach(fileMatches[0].path); setMenu(null); textarea.current?.focus(); } }} /></div>
            {fileMatches.map(f => <button key={f.path} className="menu-item" onClick={() => { attach(f.path); setMenu(null); textarea.current?.focus(); }}>
              <FileIcon path={f.path} size={14} /><span className="text"><span className="ellipsis">{f.path.split('/').pop()}</span><small>{f.path}</small></span></button>)}
            <hr />
            <button className="menu-item" disabled={!project.activePath} onClick={() => { attach(project.activePath); setMenu(null); }}><AtSign size={14} /><span className="text">Current file</span></button>
            <button className="menu-item" onClick={() => { const pr = useUi.getState().problems; setInput(v => `${v}${v ? '\n' : ''}Problems:\n${pr.slice(0, 30).map(p => `- ${p.path}:${p.line} ${p.message}`).join('\n') || '(none in open files)'}`); setMenu(null); }}><CircleAlert size={14} /><span className="text">Current problems</span></button>
          </Popover>
        </div>
        <div style={{ position: 'relative' }}>
          <button type="button" className={`mode-chip ${mode.readOnly ? 'read-only' : ''}`} data-popover-anchor aria-expanded={menu === 'mode'} title={`${mode.label}: ${mode.hint}`} onClick={() => setMenu(m => m === 'mode' ? null : 'mode')}>
            <ModeIcon size={13} /><span>{mode.label}</span>{(activeSkills.length > 0 || parallel.length > 0) && <span className="mode-extra">{[...activeSkills, ...(parallel.length ? [`+${parallel.length} agents`] : [])].join(' · ')}</span>}<ChevronDown size={11} />
          </button>
          <Popover open={menu === 'mode'} onClose={() => setMenu(null)} className="mode-pop" style={{ left: 0, bottom: 'calc(100% + 8px)' }}>
            <div className="group label">Mode</div>
            {MODES.map(m => { const Icon = MODE_ICONS[m.id]; return <button key={m.id} className="menu-item" aria-checked={m.id === s.mode} onClick={() => s.set({ mode: m.id })}>
              <Icon size={15} /><span className="text"><span>{m.label}</span><small>{m.hint}</small></span>{m.id === s.mode && <Check size={14} />}
            </button>; })}
            <hr />
            {!mode.readOnly && <label className="workflow-option"><input type="checkbox" checked={autonomous} onChange={e => setAutonomous(e.target.checked)} />
              <span>Multi-step workflow<small>Keep progress, run configured checks, and ask before applying.</small></span></label>}
            <div className="group label">Skills</div>
            <div className="skill-chips">
              {BUILTIN_SKILLS.map(k => <button key={k.id} aria-pressed={s.skills.includes(k.id)} title={k.hint} onClick={() => s.set({ skills: s.skills.includes(k.id) ? s.skills.filter(x => x !== k.id) : [...s.skills, k.id] })}>{k.label}</button>)}
              {s.customSkills.map(c => <button key={c.id} aria-pressed={s.activeCustomSkills.includes(c.id)} title={c.text} onClick={() => s.set({ activeCustomSkills: s.activeCustomSkills.includes(c.id) ? s.activeCustomSkills.filter(x => x !== c.id) : [...s.activeCustomSkills, c.id] })}><Sparkles size={11} />{c.name}</button>)}
              <button className="add" onClick={() => { setMenu(null); useUi.getState().open('settings', 'skills'); }}><Plus size={11} />Skill</button>
            </div>
            <hr />
            <div className="group label">Also run on</div>
            <div className="skill-chips">
              {[...CLI_ORDER, ...API_ORDER].filter(id => id !== s.provider).map(id => { const r = readiness(id, native, agent.providers, s.keys); const on = parallel.includes(id);
                return <button key={id} aria-pressed={on} disabled={!r.ready && native} title={r.label} onClick={() => setParallel(p => on ? p.filter(x => x !== id) : [...p, id])}>{on && <Check size={11} />}{PROVIDERS[id].label}</button>; })}
            </div>
            <p className="fine pop-note">Runs the same request on each selected engine; results open as tabs.</p>
          </Popover>
        </div>
        <span className="grow" />
        <ContextMeter usage={usage} engine={task?.engine ?? s.provider} />
        <div style={{ position: 'relative' }}>
          <button type="button" className="model-btn" data-popover-anchor aria-expanded={menu === 'model'} aria-haspopup="dialog" title={`Engine: ${PROVIDERS[s.provider].label}`} onClick={() => setMenu(m => m === 'model' ? null : 'model')}>
            {ready.tone !== 'ok' && <span className={`dot ${ready.tone}`} />}
            <span className="model-name">{modelLabel}</span>{effort && <span className="model-effort">{EFFORTS.find(e => e.id === effort)?.label}</span>}<ChevronDown size={12} />
          </button>
          <Popover open={menu === 'model'} onClose={() => setMenu(null)} className="model-pop" style={{ right: 0, bottom: 'calc(100% + 8px)' }}>
            <div className="pop-row">
              <label className="label" htmlFor="engine-select">Engine</label>
              <Select id="engine-select" label="Engine" className="engine-select" value={s.provider} onChange={v => s.set({ provider: v as ProviderId })}
                options={[...CLI_ORDER.map(id => ({ value: id as string, label: PROVIDERS[id].label, detail: readiness(id, native, agent.providers, s.keys).label, group: 'CLI' })),
                  ...API_ORDER.map(id => ({ value: id as string, label: PROVIDERS[id].label, detail: readiness(id, native, agent.providers, s.keys).label, group: 'API key' }))]} />
            </div>
            <hr />
            <div className="group label">Model</div>
            <div className="model-list">
              {[{ id: '', label: `Auto (${PROVIDERS[s.provider].label} picks)` }, ...catalog].map(m => <button key={m.id || 'default'} className="menu-item" aria-checked={m.id === model} onClick={() => setModel(m.id)}>
                <span className="text"><span>{m.label}</span>{m.id && m.label !== m.id && <small>{m.id}</small>}</span>{m.id === model && <Check size={14} />}
              </button>)}
            </div>
            <div className="model-field"><input className="field" placeholder="Custom model ID" value={catalog.some(m => m.id === model) ? '' : model} spellCheck={false} onChange={e => setModel(e.target.value)} aria-label="Custom model ID" /></div>
            <hr />
            <div className="group label">Thinking effort</div>
            <div className="effort-row" role="group" aria-label="Thinking effort">
              {EFFORTS.map(e => <button key={e.id || 'd'} aria-pressed={e.id === effort} onClick={() => setEffort(e.id)}>{e.id ? e.label.replace('Extra high', 'XHigh') : 'Auto'}</button>)}
            </div>
            <hr />
            <button className="menu-item" onClick={() => { setMenu(null); useUi.getState().open('settings', 'agents'); }}><Settings2 size={14} /><span className="text">Engines & keys</span></button>
          </Popover>
        </div>
        {running
          ? <button type="button" className="send stop" aria-label="Stop" title="Stop" onClick={() => void agent.cancel()}><Square size={10} fill="currentColor" /></button>
          : <button type="submit" className="send" aria-label="Send" title="Send · Enter" disabled={!input.trim() || agent.busy}><ArrowUp size={16} strokeWidth={2.2} /></button>}
      </div>
    </form>
    {(note || (!ready.ready && !empty)) && <p className="composer-note">
      {note || (!native ? 'Browser preview. Shark runs in the desktop app.' : `${PROVIDERS[s.provider].label}: ${ready.label.toLowerCase()}.`)}
      {native && !ready.ready && !note && <button onClick={() => useUi.getState().open('settings', 'agents')}>Set up</button>}
    </p>}
  </div>;

  return <section className={`agent-main ${empty ? 'is-empty' : ''}`} aria-label="Shark">
    <header className="agent-head">
      <span className="title" title={goal?.text}>{goal ? goal.text.split('\n')[0] : pending ? parseGoal(pending).text.split('\n')[0] : ''}</span>
      <button className="icon-btn" aria-label="Shark sessions" title="Sessions" onClick={() => s.set({ sidebarOpen: true, sidebarView: 'sessions' })}><History size={15} /></button>
      <button className="icon-btn" aria-label="New chat" title="New chat · Ctrl N" onClick={() => { agent.fresh(); setInput(''); setNote(''); setAttachments([]); textarea.current?.focus(); }}><Plus size={16} /></button>
    </header>

    {empty ? <div className="agent-hero">
      <div className="hero-inner">
        <SharkMark className="hero-mark" />
        <h1 className="hero-title">{greeting}</h1>
        {composer}
        <div className="hero-suggestions">
          {suggestions.map(({ icon: Icon, text }) => <button key={text} onClick={() => { setInput(text); textarea.current?.focus(); }}><Icon size={14} />{text}<ArrowRight size={13} className="arrow" /></button>)}
        </div>
        {!native && <p className="fine hero-note">Browser preview. Shark runs in the desktop app.</p>}
        {error && <p className="fine hero-note" role="alert">{error}</p>}
      </div>
    </div> : <>
      <div className="thread" ref={scroller} onScroll={e => { const el = e.currentTarget; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
        <div className="thread-inner" aria-live="polite">
          {siblings.length > 1 && <div className="agent-tabs" role="tablist" aria-label="Parallel agents">
            {siblings.map(t => <button key={t.id} role="tab" aria-selected={t.id === agent.activeId} onClick={() => void agent.select(t.id)}>
              <span className={`dot ${t.status === 'running' ? 'live' : t.status === 'review' ? 'warn' : t.status === 'failed' ? 'err' : t.status === 'completed' || t.status === 'applied' ? 'ok' : ''}`} />
              {PROVIDERS[t.engine as ProviderId]?.label ?? t.engine}<small>{STATUS[t.status]}</small>
            </button>)}
          </div>}
          {(() => { const g = goal ?? parseGoal(pending ?? ''); return <div className="msg-user">
            {g.continues && <div className="attached top"><CornerDownRight size={12} />Continues “{g.continues.slice(0, 60)}”</div>}
            <div className="msg-text">{g.text}</div>
            {g.files.length > 0 && <div className="attached">{g.files.map(f => <span key={f} className="ctx-chip"><FileIcon path={f} size={11} />{f.split('/').pop()}</span>)}</div>}
          </div>; })()}
          <div className="msg-shark">
            <SharkMark className={`msg-avatar ${running || pending !== null ? 'swimming' : ''}`} />
            <div className="msg-body">
              {blocks.map((b, i) => b.type === 'thinking' ? <Thinking key={i} block={b} />
                : b.type === 'steps' ? <Steps key={i} steps={b.steps} root={project.root} />
                : b.type === 'text' ? <Markdown key={i} text={b.text} />
                : b.type === 'notice' ? <p key={i} className="notice"><Info size={13} />{b.text}</p>
                : b.type === 'lifecycle' ? <Lifecycle key={i} block={b} />
                : <ErrorCallout key={i} block={b} onRetry={() => { setInput(goal?.text ?? ''); textarea.current?.focus(); }}
                    onNewChat={() => { const sum = task?.summary || goal?.text || ''; agent.fresh(); setInput(`Continue from a previous chat. Summary so far:\n${sum.slice(0, 1500)}\n\nNext: `); textarea.current?.focus(); }} />)}
              {(() => { const st = contextState(usage, task?.engine); return st?.fill != null && st.fill > 0.75 && <p className={`notice ${st.fill > 0.9 ? 'danger' : 'warn'}`}><CircleAlert size={13} />
                Context {Math.round(st.fill * 100)}% full{st.fill > 0.9 ? '. The engine will compact soon and may lose early details.' : '.'} Start a new chat to keep Shark's full attention.</p>; })()}
              {streaming && <Markdown text={streaming} streaming={!s.reduceMotion} />}
              {(pending !== null || running) &&
                <div className="working"><span className="shark-wake" aria-hidden="true"><SharkMark className="wake-fin" /></span><span className="thinking-label">{pending !== null ? 'Starting' : 'Working'}<span className="dots"><i /><i /><i /></span></span>{startedAt && running && <span className="muted elapsed">{elapsed(now / 1000 - startedAt)}</span>}</div>}
              {task?.workflow_id && <WorkflowControls task={task} />}
              {task && agent.proposal && task.proposal_id === agent.proposal.id && <ProposalCard />}
              {task && !running && task.status === 'cancelled' && <p className="fine">Stopped.</p>}
              {task && !running && startedAt && finishedAt && <p className="fine run-time">{task.status === 'cancelled' ? 'Stopped after' : task.status === 'failed' ? 'Failed after' : 'Finished in'} {elapsed(finishedAt - startedAt)}</p>}
              {task && !running && task.status === 'interrupted' && <p className="fine">Interrupted when the backend restarted.</p>}
              {task && !running && task.status === 'completed' && !agent.proposal && blocks.length > 0 && <p className="fine done-note"><Check size={12} /> Done. No file changes.</p>}
            </div>
          </div>
        </div>
      </div>
      <div className="composer-dock">
        {error && <div className="callout error" role="alert">
          <AlertCircle size={15} />
          <div className="grow">{/Required: .*optional:/.test(error) ? 'The Shark backend is older than the app (it was started before an update).' : error}{native && (!agent.connected || /Required: .*optional:|unknown_method/.test(error)) && <div className="actions"><button className="btn sm" onClick={async () => { const { restartBackend } = await import('../../lib/sharkBackend'); await restartBackend(); agent.clearError(); await agent.connect(); }}><RefreshCw size={12} />Restart backend</button></div>}</div>
          <button className="icon-btn sm" aria-label="Dismiss" onClick={() => { agent.clearError(); project.clearError(); }}><X size={12} /></button>
        </div>}
        {composer}
      </div>
    </>}
  </section>;
}

function FileDiff({ file }: { file: { path: string; before_artifact: string | null; after_artifact: string | null; before_version: string | null; after_version: string | null } }) {
  const [lines, setLines] = useState<DiffLine[] | null | 'error' | 'large'>(null);
  const kind = changeKind(file);
  useEffect(() => {
    let live = true;
    void Promise.all([readArtifact(file.before_artifact), readArtifact(file.after_artifact)])
      .then(([before, after]) => { if (!live) return; if (kind === 'create') { const all = after.replace(/\n$/, '').split('\n'); const preview: DiffLine[] = all.slice(0, 40).map((t, i) => ({ kind: 'add', text: t, new: i + 1 })); if (all.length > 40) preview.push({ kind: 'gap', text: `${all.length - 40} more lines` }); setLines(preview); } else setLines(lineDiff(before, after) ?? 'large'); })
      .catch(() => { if (live) setLines('error'); });
    return () => { live = false; };
  }, [file.before_artifact, file.after_artifact, kind]);
  if (lines === null) return <div className="inline-diff loading">Loading changes…</div>;
  if (lines === 'error') return <div className="inline-diff loading">Changes are available in the desktop app.</div>;
  if (lines === 'large') return <div className="inline-diff loading">Large change. Open the review to see it.</div>;
  if (kind === 'delete') return <div className="inline-diff loading">This file will be deleted.</div>;
  return <div className="inline-diff" role="region" aria-label={`Changes in ${file.path}`}>
    {lines.map((l, i) => l.kind === 'gap' ? <div key={i} className="dl gap">{l.text || '⋯'}</div>
      : <div key={i} className={`dl ${l.kind}`}><span className="ln">{l.kind === 'del' ? l.old : l.new}</span><span className="sign">{l.kind === 'add' ? '+' : l.kind === 'del' ? '−' : ' '}</span><code>{l.text || ' '}</code></div>)}
  </div>;
}

function ProposalCard() {
  const agent = useAgentWorkspace();
  const proposal = agent.proposal!;
  const task = agent.tasks.find(t => t.id === agent.activeId);
  const applied = proposal.status === 'applied';
  const [open, setOpen] = useState<string | null>(proposal.files.length === 1 ? proposal.files[0].path : null);
  const openReview = () => useUi.getState().set({ editorView: 'review' });
  return <div className="proposal">
    <header><GitCompareArrows size={15} />{applied ? 'Changes applied' : 'Proposed changes'}<span className="badge">{proposal.files.length} {proposal.files.length === 1 ? 'file' : 'files'}</span></header>
    <ul>{proposal.files.slice(0, 12).map(f => <li key={f.path}>
      <button onClick={() => setOpen(o => o === f.path ? null : f.path)} title={f.path} aria-expanded={open === f.path}>
        <ChevronRight size={12} className="chev" /><FileIcon path={f.path} size={13} /><span className="grow ellipsis">{f.path}</span><span className={`badge ${changeKind(f)}`}>{changeKind(f)}</span>
      </button>
      {open === f.path && <FileDiff file={f} />}
    </li>)}
      {proposal.files.length > 12 && <li className="fine" style={{ padding: '4px 6px' }}>+{proposal.files.length - 12} more in review</li>}
    </ul>
    <footer>
      <button className="btn" onClick={openReview}><Search size={13} />Full review</button>
      <button className="btn accent" disabled={applied || agent.busy || !task?.summary || proposal.status !== 'prepared'} onClick={() => void agent.apply()}>
        <Check size={14} />{applied ? 'Applied' : agent.busy ? 'Applying…' : 'Apply'}
      </button>
    </footer>
  </div>;
}
