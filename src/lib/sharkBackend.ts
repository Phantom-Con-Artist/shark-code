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
async function request<T>(method: string, params: object = {}): Promise<T> {
  if (!isTauri()) throw new BackendError('native_required', 'Open Shark Code in the desktop app to use native agent tools.');
  const id = crypto.randomUUID();
  const response = await invoke<Response<T>>('backend_request', { workspaceRoot: useProjectStore.getState().root, request: { id, method, params } });
  if (response.id !== id) throw new BackendError('protocol_error', 'The backend response did not match its request.');
  if (response.error) throw new BackendError(response.error.code, response.error.message);
  return response.result as T;
}
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
  id: string; goal: string; summary?: string | null; review_notes?: string | null; status: 'created' | 'running' | 'review' | 'applied' | 'completed' | 'cancelled' | 'interrupted' | 'failed';
  proposal_id: string | null; proposal_revision: string | null; created_at: number; proposal_status?: ChangePreview['status'];
}
export interface TaskEvent {
  sequence: number; kind: string; data: Record<string, unknown>; timestamp: number;
}
// Desktop and agent adapters call one workspace gateway. Tasks join exploration,
// impact evidence and the native changeset rather than keeping parallel state.
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
  taskContext: (id: string, query: string) => request<{ graph: GraphResult }>('task/context', { id, query }),
  propose: (id: string, changes: FileOperation[]) => request<{ task: AgentTask; proposal: ChangePreview; impact: ImpactReport }>('task/propose', { id, changes }),
  apply: (id: string) => request<{ task: AgentTask; proposal: ChangePreview; graph_refresh: string }>('task/apply', { id }),
  events: (id: string, after = 0) => request<{ events: TaskEvent[]; next_cursor: number; has_more: boolean }>('task/events', { id, after }),
  start: (id: string, model: string) => request<{ task_id: string; status: string }>('agent/start', { id, model }),
  cancel: (id: string) => request<{ task_id: string; status: string }>('agent/cancel', { id }),
};
