import { create } from 'zustand';
import { AgentMessage, AIModelConfig, AIProvider } from '../types';

export const AVAILABLE_MODELS: AIModelConfig[] = [
  { id: 'claude-3-7-sonnet', name: 'Claude 3.7 Sonnet', provider: 'anthropic', contextWindow: 200000, supportsThinking: true },
  { id: 'claude-3-5-sonnet', name: 'Claude 3.5 Sonnet', provider: 'anthropic', contextWindow: 200000, supportsThinking: false },
  { id: 'claude-3-5-haiku', name: 'Claude 3.5 Haiku', provider: 'anthropic', contextWindow: 200000, supportsThinking: false },
  { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro', provider: 'gemini', contextWindow: 1000000, supportsThinking: true },
  { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash', provider: 'gemini', contextWindow: 1000000, supportsThinking: true },
  { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', contextWindow: 128000, supportsThinking: false },
  { id: 'o3-mini', name: 'o3-mini', provider: 'openai', contextWindow: 200000, supportsThinking: true },
  { id: 'deepseek-r1', name: 'DeepSeek R1 (Ollama / Local)', provider: 'ollama', contextWindow: 64000, supportsThinking: true },
];

interface AgentState {
  messages: AgentMessage[];
  selectedModel: AIModelConfig;
  apiKeys: Record<AIProvider, string>;
  isStreaming: boolean;
  systemPrompt: string;

  setSelectedModel: (model: AIModelConfig) => void;
  setApiKey: (provider: AIProvider, key: string) => void;
  addMessage: (msg: Omit<AgentMessage, 'id' | 'timestamp'>) => string;
  updateMessageContent: (id: string, content: string, thinking?: string) => void;
  setIsStreaming: (isStreaming: boolean) => void;
  clearHistory: () => void;
}

export const useAgentStore = create<AgentState>((set) => ({
  messages: [
    {
      id: 'initial-agent-msg',
      sender: 'agent',
      content: `Hello! I am your native Shark Code agent. I have direct access to your workspace, Tree-sitter AST, Ripgrep search, and git checkpoints. What are we building or exploring today?`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ],
  selectedModel: AVAILABLE_MODELS[0],
  apiKeys: {
    anthropic: '',
    gemini: '',
    openai: '',
    ollama: 'http://localhost:11434',
    openrouter: '',
  },
  isStreaming: false,
  systemPrompt: `You are Shark Code's autonomous coding agent. You operate directly inside the user's workspace with curated tools: Tree-sitter AST analysis, sub-millisecond Ripgrep search, compiler diagnostics, and live diff generation. Provide concise, surgical edits.`,

  setSelectedModel: (selectedModel) => set({ selectedModel }),
  setApiKey: (provider, key) =>
    set((state) => ({
      apiKeys: { ...state.apiKeys, [provider]: key },
    })),
  addMessage: (msg) => {
    const id = `msg-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`;
    const newMsg: AgentMessage = {
      ...msg,
      id,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };
    set((state) => ({ messages: [...state.messages, newMsg] }));
    return id;
  },
  updateMessageContent: (id, content, thinking) => {
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, content, thinking: thinking ?? m.thinking } : m
      ),
    }));
  },
  setIsStreaming: (isStreaming) => set({ isStreaming }),
  clearHistory: () => set({ messages: [] }),
}));
