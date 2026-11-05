import { create } from 'zustand';
import { invoke, isTauri } from '@tauri-apps/api/core';

export type ProjectEntry = { path: string; directory: boolean };
export type OpenFile = { path: string; content: string; saved: string };
type DirectoryHandle = { name: string; kind: string; values(): AsyncIterable<DirectoryHandle & { getFile(): Promise<File> }>; getDirectoryHandle(name: string, options?: { create: boolean }): Promise<DirectoryHandle>; getFileHandle(name: string, options?: { create: boolean }): Promise<{ getFile(): Promise<File>; createWritable(): Promise<{ write(content: string): Promise<void>; close(): Promise<void> }> }> };
const source = import.meta.glob(['/src/**/*.{ts,tsx,css}', '/src-tauri/src/*.rs', '/package.json', '/README.md', '/index.html'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const initial = Object.fromEntries(Object.entries(source).map(([path, content]) => [path.slice(1), content]));
const STORAGE = 'shark-code.browser-files.v1';
function browserFiles(): Record<string, string> { try { return { ...initial, ...JSON.parse(localStorage.getItem(STORAGE) || '{}') }; } catch { return initial; } }
function entriesFor(files: Record<string, string>): ProjectEntry[] {
  const directories = new Set<string>();
  Object.keys(files).forEach(path => { const parts = path.split('/'); parts.pop(); while (parts.length) { directories.add(parts.join('/')); parts.pop(); } });
  return [...[...directories].map(path => ({ path, directory: true })), ...Object.keys(files).map(path => ({ path, directory: false }))];
}
function cleanPath(path: string) { if (!path || path.startsWith('/') || path.includes('\\') || path.split('/').some(p => !p || p === '.' || p === '..')) throw new Error('Use a relative file path, such as src/new-file.ts.'); return path; }
let folder: DirectoryHandle | null = null;
let initialization: Promise<void> | null = null;
async function diskHandle(path: string, create = false) {
  if (!folder) throw new Error('Open a folder first.');
  const parts = cleanPath(path).split('/'); const name = parts.pop()!;
  let parent = folder;
  for (const part of parts) parent = await parent.getDirectoryHandle(part, { create });
  return parent.getFileHandle(name, { create });
}
async function scanFolder(base: DirectoryHandle, prefix = '', depth = 0): Promise<ProjectEntry[]> {
  if (depth > 20) return [];
  const result: ProjectEntry[] = [];
  for await (const handle of base.values()) {
    if (['node_modules', '.git', 'dist', 'target', '.taste-skill'].includes(handle.name)) continue;
    const path = prefix + handle.name;
    result.push({ path, directory: handle.kind === 'directory' });
    if (handle.kind === 'directory') result.push(...await scanFolder(handle, path + '/', depth + 1));
    if (result.length > 5000) break;
  }
  return result;
}
interface ProjectState {
  name: string; root: string; kind: 'browser' | 'folder' | 'native'; entries: ProjectEntry[]; tabs: OpenFile[]; activePath: string; error: string; notice: string; busy: boolean;
  initialize(): Promise<void>; openFolder(path?: string): Promise<void>; openFile(path: string): Promise<void>; edit(path: string, content: string): void; save(path: string): Promise<void>; createFile(path: string): Promise<void>; closeFile(path: string): void; reloadFile(path: string): Promise<void>; clearError(): void;
}
export const useProjectStore = create<ProjectState>((set, get) => ({
  name: 'shark-code', root: 'Browser workspace', kind: 'browser', entries: entriesFor(browserFiles()), tabs: [], activePath: '', error: '', notice: '', busy: false,
  initialize: () => {
    if (initialization) return initialization;
    initialization = (async () => {
      if (isTauri()) await get().openFolder();
      await get().openFile('src/App.tsx');
    })();
    return initialization;
  },
  openFolder: async path => {
    if (get().tabs.some(t => t.content !== t.saved)) { set({ error: 'Save your edited files before switching projects.' }); return; }
    set({ busy: true, error: '' });
    try {
      if (isTauri()) {
        const project = await invoke<{ name: string; root: string; entries: ProjectEntry[] }>('workspace_open', { path: path || null });
        folder = null; set({ ...project, kind: 'native', tabs: [], activePath: '', notice: 'Connected to your local project' });
      } else {
        const picker = (window as unknown as { showDirectoryPicker?: (options: { mode: string }) => Promise<DirectoryHandle> }).showDirectoryPicker;
        if (!picker) throw new Error('Folder access is unavailable in this browser. You can edit and save the browser workspace, or use the desktop app for local files.');
        const selected = await picker({ mode: 'readwrite' });
        const entries = await scanFolder(selected);
        folder = selected;
        set({ name: selected.name, root: selected.name, entries, kind: 'folder', tabs: [], activePath: '', notice: 'Folder connected. Save writes to your selected folder.' });
      }
    } catch (e) { if (!(e instanceof DOMException && e.name === 'AbortError')) set({ error: String(e) }); }
    finally { set({ busy: false }); }
  },
  openFile: async path => {
    if (get().tabs.some(t => t.path === path)) { set({ activePath: path }); return; }
    set({ error: '' });
    try {
      const content = get().kind === 'native' ? await invoke<string>('workspace_read', { path }) : get().kind === 'folder' ? await (await (await diskHandle(path)).getFile()).text() : browserFiles()[path];
      if (content === undefined) throw new Error('File could not be found.');
      if (content.length > 2 * 1024 * 1024 || content.includes('\0')) throw new Error('Open a text file smaller than 2 MB.');
      set(s => ({ tabs: [...s.tabs.filter(t => t.path !== path), { path, content, saved: content }], activePath: path }));
    } catch (e) { set({ error: String(e) }); }
  },
  edit: (path, content) => set(s => ({ tabs: s.tabs.map(t => t.path === path ? { ...t, content } : t), notice: '' })),
  save: async path => {
    const file = get().tabs.find(t => t.path === path); if (!file) return;
    set({ busy: true, error: '' });
    try {
      if (get().kind === 'native') await invoke('workspace_write', { path, content: file.content, expected: file.saved });
      else if (get().kind === 'folder') {
        const handle = await diskHandle(path);
        if (await (await handle.getFile()).text() !== file.saved) throw new Error('File changed on disk. Reopen it before saving.');
        const writer = await handle.createWritable(); await writer.write(file.content); await writer.close();
      } else { const all = browserFiles(); all[path] = file.content; localStorage.setItem(STORAGE, JSON.stringify(all)); }
      set(s => ({ tabs: s.tabs.map(t => t.path === path ? { ...t, saved: file.content } : t), notice: get().kind === 'browser' ? 'Saved in this browser' : 'Saved to disk' }));
    } catch (e) { set({ error: String(e) }); }
    finally { set({ busy: false }); }
  },
  createFile: async input => {
    try {
      const path = cleanPath(input.trim());
      if (get().entries.some(e => e.path === path)) throw new Error('That path already exists. Choose another name.');
      if (get().kind === 'native') await invoke('workspace_write', { path, content: '', expected: null });
      else if (get().kind === 'folder') {
        const all = await scanFolder(folder!);
        if (all.some(e => e.path === path)) throw new Error('That file already exists on disk.');
        const writer = await (await diskHandle(path, true)).createWritable(); await writer.close();
      } else { const all = browserFiles(); all[path] = ''; localStorage.setItem(STORAGE, JSON.stringify(all)); }
      const nextEntries = entriesFor(Object.fromEntries([...get().entries.filter(e => !e.directory).map(e => [e.path, '']), [path, '']]));
      set(s => ({ entries: nextEntries, tabs: [...s.tabs, { path, content: '', saved: '' }], activePath: path, notice: get().kind === 'browser' ? 'File created in browser workspace' : 'File created on disk', error: '' }));
    } catch (e) { set({ error: String(e) }); }
  },
  reloadFile: async path => {
    const original = get().tabs;
    set(s => ({ tabs: s.tabs.filter(t => t.path !== path) }));
    await get().openFile(path);
    if (get().error) set({ tabs: original });
  },
  closeFile: path => {
    const file = get().tabs.find(t => t.path === path);
    if (file && file.content !== file.saved) { set({ error: 'Save this file before closing it.' }); return; }
    set(s => { const tabs = s.tabs.filter(t => t.path !== path); return { tabs, activePath: s.activePath === path ? tabs[tabs.length - 1]?.path || '' : s.activePath }; });
  },
  clearError: () => set({ error: '' }),
}));
