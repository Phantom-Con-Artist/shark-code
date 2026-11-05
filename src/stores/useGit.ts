import { create } from 'zustand';
import { sharkGit, type GitStatus } from '../lib/sharkBackend';
import { useProjectStore } from './useProjectStore';

/** Shared git status for decorations (Explorer, tabs, status bar) and the Source Control view. */
interface GitState { status: GitStatus | null; byPath: Record<string, string>; dirtyDirs: Record<string, string>; refresh(): Promise<void> }
const RANK: Record<string, number> = { conflict: 5, deleted: 4, modified: 3, renamed: 3, added: 2, untracked: 1 };
export const useGit = create<GitState>(set => ({
  status: null, byPath: {}, dirtyDirs: {},
  refresh: async () => {
    if (useProjectStore.getState().kind !== 'native') return;
    try {
      const status = await sharkGit.status();
      const byPath: Record<string, string> = {}, dirtyDirs: Record<string, string> = {};
      for (const f of status.files) {
        byPath[f.path] = f.status;
        const parts = f.path.split('/');
        for (let i = 1; i < parts.length; i++) {
          const dir = parts.slice(0, i).join('/');
          if ((RANK[f.status] ?? 0) > (RANK[dirtyDirs[dir]] ?? 0)) dirtyDirs[dir] = f.status;
        }
      }
      set({ status, byPath, dirtyDirs });
    } catch { set({ status: null, byPath: {}, dirtyDirs: {} }); }
  },
}));
export const GIT_LETTER: Record<string, string> = { modified: 'M', added: 'A', deleted: 'D', renamed: 'R', untracked: 'U', conflict: '!' };
