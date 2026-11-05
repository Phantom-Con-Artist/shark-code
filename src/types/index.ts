export type AIProvider = 'anthropic' | 'gemini' | 'openai' | 'ollama' | 'openrouter';

export interface AIModelConfig {
  id: string;
  name: string;
  provider: AIProvider;
  contextWindow: number;
  supportsThinking?: boolean;
}

export interface FileNode {
  name: string;
  path: string;
  isDirectory: boolean;
  size?: number;
  children?: FileNode[];
}

export interface EditorTab {
  id: string;
  path: string;
  name: string;
  content: string;
  isDirty: boolean;
  language: string;
  cursorPosition?: { line: number; column: number };
}

export interface AgentMessage {
  id: string;
  sender: 'user' | 'agent' | 'system';
  content: string;
  timestamp: string;
  thinking?: string;
  toolCalls?: ToolCall[];
  proposedDiffs?: ProposedDiff[];
}

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: 'pending' | 'running' | 'success' | 'error';
  result?: string;
}

export interface ProposedDiff {
  filePath: string;
  originalContent: string;
  newContent: string;
  status: 'pending' | 'accepted' | 'rejected';
}

export interface SearchResult {
  filePath: string;
  lineNumber: number;
  lineContent: string;
  matchStart: number;
  matchEnd: number;
}
