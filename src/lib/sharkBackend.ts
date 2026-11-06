import { invoke, isTauri } from '@tauri-apps/api/core';
import { useProjectStore } from '../stores/useProjectStore';

export class BackendError extends Error {
  constructor(public readonly code: string, message: string) { super(message); this.name = 'BackendError'; }
}
export interface FileSnapshot {
  path: string; version: string; artifact_id: string; content: string;
  start_line: number; total_lines: number; truncated: boolean; cache_hit: boolean;
}
export type SurgicalEdit =
  | { kind: 'replace'; old: string; new: string; expected_matches?: number }
  | { kind: 'range'; start_byte: number; end_byte: number; old: string; new: string };
export type FileOperation =
  | { kind: 'create'; path: string; content: string }
  | { kind: 'edit'; path: string; expected_version: string; edits: SurgicalEdit[] }
  | { kind: 'delete'; path: string; expected_version: string };
export interface ChangePreview {
  id: string; status: 'prepared' | 'applying' | 'applied' | 'reverting' | 'reverted';
  files: { path: string; before_version: string | null; after_version: string | null;
    before_artifact: string | null; after_artifact: string | null; before_lines: number; after_lines: number }[];
}
export interface SyntaxOutline {
  path: string; version: string; artifact_id: string; language: string;
  syntax_errors: boolean; truncated: boolean; cache_hit: boolean;
  symbols: { name: string; qualified_name: string; kind: string; start_byte: number; end_byte: number;
    start_line: number; end_line: number; calls_truncated: boolean;
    calls: { expression: string; line: number; resolution: 'unresolved_syntax' }[] }[];
  imports: { source: string; line: number; resolution: 'unresolved_syntax' }[];
}
type Response<T> = { id: string; result: T; error?: never } | { id: string; result?: never; error: { code: string; message: string } };
export async function request<T>(method: string, params: object = {}): Promise<T> {
  if (!isTauri()) throw new BackendError('native_required', 'Open Shark Code in the desktop app to use native agent tools.');
  const id = crypto.randomUUID();
  const response = await invoke<Response<T>>('backend_request', { workspaceRoot: useProjectStore.getState().root, request: { id, method, params } });
  if (response.id !== id) throw new BackendError('protocol_error', 'The backend response did not match its request.');
  if (response.error) throw new BackendError(response.error.code, response.error.message);
  return response.result as T;
}
export const EXPECTED_RUNTIME = 7;
export const restartBackend = () => invoke('backend_restart');
export const sharkBackend = {
  capabilities: () => request<Record<string, unknown>>('capabilities'),
  list: (offset = 0, limit = 200) => request<{ files: { path: string; bytes: number }[]; total: number; next_offset: number | null; truncated: boolean }>('workspace/list', { offset, limit }),
  read: (path: string, start_line = 1, limit = 200) => request<FileSnapshot>('file/read', { path, start_line, limit }),
  readArtifact: (id: string, start_line = 1, limit = 200) => request<FileSnapshot>('artifact/read', { id, start_line, limit }),
  outline: (path: string) => request<SyntaxOutline>('code/outline', { path }),
  search: (pattern: string, limit = 50) => request<{ hits: { path: string; line: number; text: string; version: string }[]; truncated: boolean; skipped_files: string[] }>('code/search', { pattern, limit }),
  cacheStats: () => request<{ hits: number; misses: number }>('cache/stats'),
  preview: (changes: FileOperation[]) => request<ChangePreview>('changes/preview', { changes }),
  apply: (id: string) => request<ChangePreview>('changes/apply', { id }),
  revert: (id: string) => request<ChangePreview>('changes/revert', { id }),
  pending: () => request<{ ids: string[] }>('changes/pending'),
  recover: (id: string) => request<ChangePreview>('changes/recover', { id }),
};

export interface GraphNode {
  id: string; label: string; kind: string; path: string | null; location: string;
  version: string | null; artifact_id: string | null; external: boolean;
}
export interface GraphEdge {
  source: string; target: string; relation: string;
  confidence: 'EXTRACTED' | 'INFERRED' | 'UNKNOWN'; evidence: string;
}
export interface GraphResult {
  revision: string; provider: 'graphify'; seeds: GraphNode[]; nodes: GraphNode[];
  edges: GraphEdge[]; coverage: Record<string, unknown>; truncated: boolean;
}
export interface ImpactReport {
  revision: string; changed_paths: string[]; seed_count: number;
  affected: { node: GraphNode; distance: number; evidence_path: GraphEdge[]; confidence: string }[];
  coverage: Record<string, unknown>; truncated: boolean; analysis: string;
}
export interface AgentTask {
  id: string; goal: string; summary?: string | null; review_notes?: string | null; status: 'created' | 'running' | 'review' | 'applied' | 'completed' | 'cancelled' | 'interrupted' | 'failed' | 'paused' | 'waiting_human' | 'blocked';
  proposal_id: string | null; proposal_revision: string | null; created_at: number; proposal_status?: ChangePreview['status'];
  engine?: string; mode?: string; model?: string; group?: string | null; workflow_id?: string;
}
export interface ProviderStatus { id: string; label: string; kind: 'byok' | 'cli'; available: boolean; env_configured?: boolean; installed?: boolean; reason?: string }
export interface SlashCommand { name: string; provider: string; scope: string; kind: 'native' | 'prompt'; description: string; argument_hint: string; body?: string }
export interface TaskEvent {
  sequence: number; kind: string; data: Record<string, unknown>; timestamp: number;
}
// Desktop and agent adapters call one workspace gateway. Tasks join exploration,
// impact evidence and the native changeset rather than keeping parallel state.
export type GitFile = { path: string; staged: boolean; index: string; worktree: string; status: string };
export type GitStatus = { repo: boolean; branch: string | null; ahead?: number; behind?: number; files: GitFile[] };
export type StaticAnalyzer = 'python-syntax' | 'code-stats' | 'ast-grep' | 'semgrep' | 'scc' | 'ctags';
export interface StaticAnalysisResult {
  tool: StaticAnalyzer;
  status: 'completed' | 'unavailable' | 'timeout' | 'failed';
  message?: string;
  findings?: { path: string; line: number | null; column: number | null; message: string }[];
  statistics?: Record<string, { files: number; bytes: number; lines: number }>;
  output?: string;
  stderr?: string;
  exit_code?: number;
  skipped?: string[];
  skipped_count?: number;
  partial?: boolean;
  truncated?: boolean;
  bytes_analyzed?: number;
  path_prefix?: string;
}
export interface IntelligenceReport {
  schema: string; context_id: string; revision: string; kind: string; source_manifest_artifact_id: string | null;
  provider: { id: string; version: string }; status: 'completed' | 'partial';
  coverage: Record<string, unknown>; data: Record<string, unknown>; artifact_id: string; truncated: boolean;
}
export type IntelligenceOperation = 'status' | 'index' | 'structure' | 'search' | 'explain' | 'dependencies' |
  'impact' | 'quality' | 'security' | 'architecture' | 'history' | 'runtime' | 'context';
export const sharkIntelligence = {
  project: (operation: IntelligenceOperation, params: Record<string, unknown> = {}) =>
    request<IntelligenceReport>('intelligence/' + operation, params),
  artifact: (id: string, section?: string, offset = 0, limit = 50) =>
    request<Record<string, unknown>>('intelligence/artifact', { id, ...(section ? { section } : {}), offset, limit }),
  analyze: (tool: StaticAnalyzer, options: { pattern?: string; language?: string } = {}) =>
    request<StaticAnalysisResult>('tools/analyze', { tool, ...options }),
};
export const sharkGit = {
  status: () => request<GitStatus>('git/status'),
  diff: (path?: string, staged = false) => request<{ diff: string; truncated: boolean }>('git/diff', { ...(path ? { path } : {}), staged }),
  log: (limit = 30) => request<{ commits: { hash: string; short: string; author: string; time: string; subject: string }[] }>('git/log', { limit }),
  stage: (paths: string[]) => request<GitStatus>('git/stage', { paths }),
  unstage: (paths: string[]) => request<GitStatus>('git/unstage', { paths }),
  commit: (message: string) => request<{ commit: { short: string; subject: string }; status: GitStatus }>('git/commit', { message }),
  tools: () => request<{ tools: { id: string; label: string; purpose: string; available: boolean; builtin?: boolean; callable?: boolean; version: string | null; install: string; tasks: { label: string; command: string }[] }[] }>('tools/detect'),
  branches: () => request<{ branches: { name: string; current: boolean }[] }>('git/branches'),
  checkout: (name: string, create = false) => request<GitStatus>('git/checkout', { name, create }),
  sync: (action: 'fetch' | 'pull' | 'push') => request<{ output: string; status: GitStatus }>('git/sync', { action }),
  deps: () => request<{ groups: { manager: string; manifest: string; section: string; items: { name: string; version: string }[] }[] }>('deps/list'),
};
export interface PickedElement { url: string; selector: string; tag: string; id: string; classes: string[]; text: string; html: string; rect: { x: number; y: number; w: number; h: number } }
export interface SourceMatch { path: string; line: number; snippet: string; score: number; matched: string[] }
export interface PageCheck { available: boolean; error?: string; url?: string; status?: number | null; title?: string; console?: { level: string; message: string }[]; failed_requests?: { url: string; error: string }[]; screenshot?: string; text?: string }
export const sharkBrowser = {
  serve: (target = 'workspace') => request<{ url: string; base: string; target: string }>('browser/serve', { target }),
  locate: (pick: PickedElement) => request<{ matches: SourceMatch[] }>('browser/locate', { pick }),
  check: (url: string) => request<PageCheck>('browser/check', { url }),
};
export const sharkLsp = {
  servers: () => request<{ servers: Record<string, string | null>; root: string }>('lsp/start', {}),
  start: (language: string) => request<{ server: string; root: string; triggers: string[]; signature_triggers: string[] }>('lsp/start', { language }),
  request: <T = unknown>(language: string, method: string, params: unknown, timeout?: number) => request<{ result: T }>('lsp/request', { language, method, params, ...(timeout ? { timeout } : {}) }).then(r => r.result),
  notify: (language: string, method: string, params: unknown) => request<{ ok: boolean }>('lsp/notify', { language, method, params }),
  poll: () => request<{ diagnostics: Record<string, { range: { start: { line: number; character: number }; end: { line: number; character: number } }; severity?: number; message: string; source?: string; code?: string | number }[]> }>('lsp/poll', {}),
};
export interface WorkflowStep {
  id: string; kind: 'agent' | 'intelligence' | 'check' | 'human'; title: string;
  depends_on: string[]; status: string; attempts: number; summary: string; artifact_id?: string;
  exit_code?: number; repairs: number;
}
export interface Workflow {
  id: string; task_id: string; status: string; version: number; goal: string;
  steps: WorkflowStep[]; step_count: number; next_step_offset: number | null;
  gate: { id: string; kind: 'question' | 'approval'; question: string; step_id?: string } | null;
  attempts: number; agent_runs: number; active_seconds: number; summary: string;
  budget: { max_attempts: number; max_agent_runs: number; max_active_seconds: number };
}
export const sharkWorkflows = {
  create: (goal: string, run: Record<string, unknown>, steps?: Record<string, unknown>[]) =>
    request<{ workflow: Workflow; task: AgentTask }>('workflow/create', { goal, run, ...(steps ? { steps } : {}) }),
  get: (id: string, offset = 0) => request<Workflow>('workflow/get', { id, offset }),
  start: (id: string, apiKey?: string) => request<Workflow>('workflow/start', { id, ...(apiKey ? { api_key: apiKey } : {}) }),
  resume: (id: string, apiKey?: string, retryFailed = false) =>
    request<Workflow>('workflow/resume', { id, retry_failed: retryFailed, ...(apiKey ? { api_key: apiKey } : {}) }),
  pause: (id: string) => request<Workflow>('workflow/pause', { id }),
  cancel: (id: string) => request<Workflow>('workflow/cancel', { id }),
  respond: (id: string, gateId: string, decision: 'answer' | 'approve' | 'reject', answer = '') =>
    request<Workflow>('workflow/respond', { id, gate_id: gateId, decision, answer }),
  step: (id: string, stepId: string) => request<Record<string, unknown>>('workflow/step', { id, step_id: stepId }),
};
export const sharkWorkspace = {
  tasks: () => request<{ tasks: AgentTask[]; has_more: boolean }>('task/list'),
  context: (query: string, limit = 10) => request<{ query: string; graph: GraphResult; next_actions: string[]; source_policy: string }>('workspace/context', { query, limit }),
  index: (force = false) => request<{ revision: string; node_count: number; edge_count: number; coverage: Record<string, unknown> }>('graph/index', { force }),
  query: (query: string, limit = 20) => request<GraphResult>('graph/query', { query, limit }),
  impact: (paths: string[], depth = 3) => request<ImpactReport>('graph/impact', { paths, depth }),
  symbolImpact: (node_id: string, depth = 3) => request<ImpactReport>('graph/impact', { node_id, depth }),
  analyze: (id: string) => request<{ proposal: ChangePreview; impact: ImpactReport }>('changes/analyze', { id }),
  createTask: (goal: string) => request<AgentTask>('task/create', { goal }),
  task: (id: string) => request<AgentTask>('task/get', { id }),
  deleteTask: (id: string) => request<{ ok: boolean }>('task/delete', { id }),
  taskContext: (id: string, query: string) => request<{ graph: GraphResult }>('task/context', { id, query }),
  propose: (id: string, changes: FileOperation[]) => request<{ task: AgentTask; proposal: ChangePreview; impact: ImpactReport }>('task/propose', { id, changes }),
  apply: (id: string) => request<{ task: AgentTask; proposal: ChangePreview; graph_refresh: string }>('task/apply', { id }),
  events: (id: string, after = 0, limit = 100) => request<{ events: TaskEvent[]; next_cursor: number; has_more: boolean }>('task/events', { id, after, limit }),
  start: (id: string, run: { model: string; provider: string; api_key?: string; effort?: string; mode?: string; skills?: string[]; custom_skills?: string[]; group?: string }) => request<{ task_id: string; status: string }>('agent/start', { id, ...run }),
  providers: () => request<{ providers: ProviderStatus[] }>('agent/providers'),
  commands: () => request<{ commands: SlashCommand[] }>('agent/commands'),
  models: (provider: string) => request<{ models: { id: string; label: string }[] }>('agent/models', { provider }),
  cancel: (id: string) => request<{ task_id: string; status: string }>('agent/cancel', { id }),
};
