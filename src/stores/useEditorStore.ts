import { create } from 'zustand';
import { EditorTab, ProposedDiff } from '../types';

interface EditorState {
  tabs: EditorTab[];
  activeTabId: string | null;
  activeDiff: ProposedDiff | null;
  cursorPosition: { line: number; column: number };

  openTab: (tab: Omit<EditorTab, 'id' | 'isDirty'>) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  updateContent: (id: string, content: string) => void;
  setCursorPosition: (pos: { line: number; column: number }) => void;
  setActiveDiff: (diff: ProposedDiff | null) => void;
  acceptDiff: (filePath: string) => void;
  rejectDiff: () => void;
}

function getLanguageFromPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'ts':
    case 'tsx':
      return 'typescript';
    case 'js':
    case 'jsx':
      return 'javascript';
    case 'rs':
      return 'rust';
    case 'json':
      return 'json';
    case 'html':
      return 'html';
    case 'css':
      return 'css';
    case 'md':
      return 'markdown';
    case 'py':
      return 'python';
    case 'toml':
      return 'toml';
    default:
      return 'plaintext';
  }
}

export const useEditorStore = create<EditorState>((set, get) => ({
  tabs: [
    {
      id: 'welcome-tab',
      path: '/home/subhradeep/Development/shark code/README.md',
      name: 'README.md',
      content: `# Shark Code\n\nAgent-First Code Editor built with Tauri 2 + Rust + React.\n\n### Core Primitives\n- Curated Agent Tools (AST, Ripgrep, Diagnostics)\n- BYOK Direct Multi-Provider Client (Anthropic, Gemini, OpenAI, Ollama)\n- Agent Client Protocol (ACP) for Claude Code, Codex, and Gemini\n- Hardware-backed OS Keychain Credential Management`,
      isDirty: false,
      language: 'markdown',
      cursorPosition: { line: 1, column: 1 },
    },
  ],
  activeTabId: 'welcome-tab',
  activeDiff: null,
  cursorPosition: { line: 1, column: 1 },

  openTab: (tabData) => {
    const existing = get().tabs.find((t) => t.path === tabData.path);
    if (existing) {
      set({ activeTabId: existing.id });
      return;
    }
    const newTab: EditorTab = {
      ...tabData,
      id: `tab-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
      isDirty: false,
      language: tabData.language || getLanguageFromPath(tabData.path),
    };
    set((state) => ({
      tabs: [...state.tabs, newTab],
      activeTabId: newTab.id,
    }));
  },

  closeTab: (id) => {
    set((state) => {
      const filtered = state.tabs.filter((t) => t.id !== id);
      let nextActive = state.activeTabId;
      if (state.activeTabId === id) {
        nextActive = filtered.length > 0 ? filtered[filtered.length - 1].id : null;
      }
      return { tabs: filtered, activeTabId: nextActive };
    });
  },

  setActiveTab: (id) => set({ activeTabId: id }),

  updateContent: (id, content) => {
    set((state) => ({
      tabs: state.tabs.map((tab) =>
        tab.id === id ? { ...tab, content, isDirty: true } : tab
      ),
    }));
  },

  setCursorPosition: (pos) => set({ cursorPosition: pos }),

  setActiveDiff: (diff) => set({ activeDiff: diff }),

  acceptDiff: (filePath) => {
    const { activeDiff, tabs } = get();
    if (!activeDiff) return;
    const targetTab = tabs.find((t) => t.path === filePath);
    if (targetTab) {
      get().updateContent(targetTab.id, activeDiff.newContent);
    }
    set({ activeDiff: null });
  },

  rejectDiff: () => set({ activeDiff: null }),
}));
