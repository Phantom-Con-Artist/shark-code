import { create } from 'zustand';
import { FileNode } from '../types';

interface WorkspaceState {
  rootPath: string;
  projectName: string;
  fileTree: FileNode[];
  expandedPaths: Set<string>;
  activeActivity: 'explorer' | 'search' | 'agent' | 'terminal' | 'settings';
  
  setRootPath: (path: string) => void;
  setFileTree: (tree: FileNode[]) => void;
  toggleFolder: (path: string) => void;
  setActiveActivity: (activity: 'explorer' | 'search' | 'agent' | 'terminal' | 'settings') => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  rootPath: '/home/subhradeep/Development/shark code',
  projectName: 'shark-code',
  fileTree: [],
  expandedPaths: new Set(['/home/subhradeep/Development/shark code', '/home/subhradeep/Development/shark code/src']),
  activeActivity: 'explorer',

  setRootPath: (path) => set({ rootPath: path, projectName: path.split('/').filter(Boolean).pop() || 'workspace' }),
  setFileTree: (fileTree) => set({ fileTree }),
  toggleFolder: (path) =>
    set((state) => {
      const next = new Set(state.expandedPaths);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return { expandedPaths: next };
    }),
  setActiveActivity: (activeActivity) => set({ activeActivity }),
}));
