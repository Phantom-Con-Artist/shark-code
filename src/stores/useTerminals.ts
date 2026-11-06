import { create } from 'zustand';

export interface TerminalTab { id: string; title: string }
interface TerminalsState {
  tabs: TerminalTab[]; activeId: string;
  add(): string;
  remove(id: string): void;
  setActive(id: string): void;
  rename(id: string, title: string): void;
  /** The active tab's id, creating a first tab if none exists yet. */
  ensureActive(): string;
}

let counter = 0;

export const useTerminals = create<TerminalsState>((set, get) => ({
  tabs: [], activeId: '',
  add: () => {
    const n = ++counter;
    const id = `term-${n}`;
    set(s => ({ tabs: [...s.tabs, { id, title: `bash ${n}` }], activeId: id }));
    return id;
  },
  remove: id => set(s => {
    const i = s.tabs.findIndex(t => t.id === id);
    const tabs = s.tabs.filter(t => t.id !== id);
    const activeId = s.activeId !== id ? s.activeId : (tabs[Math.min(i, tabs.length - 1)]?.id ?? '');
    return { tabs, activeId };
  }),
  setActive: id => set({ activeId: id }),
  rename: (id, title) => set(s => ({ tabs: s.tabs.map(t => t.id === id ? { ...t, title } : t) })),
  ensureActive: () => {
    const s = get();
    if (s.activeId && s.tabs.some(t => t.id === s.activeId)) return s.activeId;
    if (s.tabs.length) { set({ activeId: s.tabs[0].id }); return s.tabs[0].id; }
    return get().add();
  },
}));
