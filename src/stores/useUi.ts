import { create } from 'zustand';

export type Dialog = null | 'palette' | 'files' | 'settings';
export type Problem = { path: string; line: number; column: number; message: string; severity: 'error' | 'warning'; source: string };
interface Ui {
  dialog: Dialog; settingsSection: 'appearance' | 'agents' | 'skills' | 'editor' | 'keys';
  editorView: 'file' | 'review'; resolvedTheme: 'light' | 'dark'; reveal: { path: string; line: number } | null;
  composerFocus: number; draft: { text: string; nonce: number } | null;
  panelTab: 'terminal' | 'problems'; problems: Problem[]; mdMode: 'edit' | 'split' | 'preview';
  open(dialog: Dialog, section?: Ui['settingsSection']): void;
  set(patch: Partial<Omit<Ui, 'open' | 'set'>>): void;
}
export const useUi = create<Ui>(set => ({
  dialog: null, settingsSection: 'appearance', editorView: 'file', resolvedTheme: 'dark', reveal: null,
  composerFocus: 0, draft: null, panelTab: 'terminal', problems: [], mdMode: 'split',
  open: (dialog, section) => set(s => ({ dialog, settingsSection: section ?? s.settingsSection })),
  set: patch => set(patch),
}));
