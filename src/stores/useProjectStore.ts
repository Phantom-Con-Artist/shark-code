import { create } from 'zustand';
import { invoke, isTauri } from '@tauri-apps/api/core';

export type ProjectEntry = { path: string; directory: boolean };
export type OpenFile = { path: string; content: string; saved: string };
export type SearchHit = { path: string; line: number; text: string };
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
  refreshFromDisk(paths: string[]): Promise<void>;
  name: string; root: string; kind: 'browser' | 'folder' | 'native'; entries: ProjectEntry[]; tabs: OpenFile[]; activePath: string; error: string; notice: string; busy: boolean;
  initialize(): Promise<void>; openFolder(path?: string): Promise<void>; pickFolder(): Promise<void>; openFile(path: string): Promise<void>; edit(path: string, content: string): void; save(path: string): Promise<void>; createFile(path: string): Promise<void>; closeFile(path: string, force?: boolean): void; reloadFile(path: string): Promise<void>; clearError(): void;
  history: string[]; historyIndex: number; navigating: boolean; navigate(delta: -1 | 1): Promise<void>;
  refresh(): Promise<void>; searchText(query: string): Promise<SearchHit[]>; readText(path: string): Promise<string | null>;
}
export const useProjectStore = create<ProjectState>((set, get) => ({
  refreshFromDisk: async paths => {
    if (get().kind !== 'native') return;
    const root = get().root;
    const original = get().tabs;
    try {
      const project = await invoke<{ name: string; root: string; entries: ProjectEntry[] }>('workspace_refresh', { expectedRoot: root });
      if (get().root !== root) return;
      set({ entries: project.entries });
      for (const file of original.filter(f => paths.includes(f.path) && f.content === f.saved)) {
        if (!project.entries.some(e => e.path === file.path && !e.directory)) { get().closeFile(file.path); continue; }
        const content = await invoke<string>('workspace_read', { path: file.path });
        if (get().root !== root) return;
        set(s => ({ tabs: s.tabs.map(t => t.path === file.path && t.content === file.content && t.saved === file.saved ? { ...t, content, saved: content } : t) }));
      }
    } catch (e) { if (get().root === root) set({ error: `Proposal applied, but refreshing the editor failed: ${e instanceof Error ? e.message : String(e)}` }); }
  },
  history: [], historyIndex: -1, navigating: false,
  navigate: async delta => {
    const { history, historyIndex } = get(); const next = historyIndex + delta;
    if (next < 0 || next >= history.length) return;
    set({ historyIndex: next, navigating: true });
    await get().openFile(history[next]);
    set({ navigating: false });
  },
  name: 'shark-code', root: 'Browser workspace', kind: 'browser', entries: entriesFor(browserFiles()), tabs: [], activePath: '', error: '', notice: '', busy: false,
  initialize: () => {
    if (initialization) return initialization;
    initialization = (async () => {
      if (isTauri()) await get().openFolder();
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
  pickFolder: async () => {
    if (!isTauri()) { await get().openFolder(); return; }
    try {
      const { open } = await import('@tauri-apps/plugin-dialog');
      const selected = await open({ directory: true, multiple: false, title: 'Open Folder' });
      if (typeof selected === 'string') await get().openFolder(selected);
    } catch (e) { set({ error: String(e) }); }
  },
  openFile: async path => {
    const record = () => { const st = get(); if (st.navigating || st.history[st.historyIndex] === path) return; const history = [...st.history.slice(0, st.historyIndex + 1), path].slice(-50); set({ history, historyIndex: history.length - 1 }); };
    if (get().tabs.some(t => t.path === path)) { set({ activePath: path }); record(); return; }
    set({ error: '' });
    try {
      const content = get().kind === 'native' ? await invoke<string>('workspace_read', { path }) : get().kind === 'folder' ? await (await (await diskHandle(path)).getFile()).text() : browserFiles()[path];
      if (content === undefined) throw new Error('File could not be found.');
      if (content.length > 2 * 1024 * 1024 || content.includes('\0')) throw new Error('Open a text file smaller than 2 MB.');
      set(s => ({ tabs: [...s.tabs.filter(t => t.path !== path), { path, content, saved: content }], activePath: path }));
      record();
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
      const nextEntries = get().kind === 'native' ? (await invoke<{ entries: ProjectEntry[] }>('workspace_refresh', { expectedRoot: get().root })).entries : entriesFor(Object.fromEntries([...get().entries.filter(e => !e.directory).map(e => [e.path, '']), [path, '']]));
      set(s => ({ entries: nextEntries, tabs: [...s.tabs, { path, content: '', saved: '' }], activePath: path, notice: get().kind === 'browser' ? 'File created in browser workspace' : 'File created on disk', error: '' }));
    } catch (e) { set({ error: String(e) }); }
  },
  reloadFile: async path => {
    const original = get().tabs;
    set(s => ({ tabs: s.tabs.filter(t => t.path !== path) }));
    await get().openFile(path);
    if (get().error) set({ tabs: original });
  },
  closeFile: (path, force = false) => {
    const file = get().tabs.find(t => t.path === path);
    if (file && file.content !== file.saved && !force) { set({ error: 'Save this file before closing it.' }); return; }
    set(s => { const tabs = s.tabs.filter(t => t.path !== path); return { tabs, activePath: s.activePath === path ? tabs[tabs.length - 1]?.path || '' : s.activePath }; });
  },
  clearError: () => set({ error: '' }),
  readText: async path => {
    const open = get().tabs.find(t => t.path === path); if (open) return open.content;
    try {
      if (get().kind === 'native') return await invoke<string>('workspace_read', { path });
      if (get().kind === 'folder') return await (await (await diskHandle(path)).getFile()).text();
      return browserFiles()[path] ?? null;
    } catch { return null; }
  },
  refresh: async () => {
    const { kind, root } = get();
    try {
      if (kind === 'native') { const project = await invoke<{ entries: ProjectEntry[] }>('workspace_refresh', { expectedRoot: root }); if (get().root === root) set({ entries: project.entries }); }
      else if (kind === 'folder' && folder) set({ entries: await scanFolder(folder) });
      else set({ entries: entriesFor(browserFiles()) });
    } catch (e) { set({ error: String(e) }); }
  },
  searchText: async query => {
    const needle = query.trim(); if (!needle) return [];
    const { kind } = get();
    if (kind === 'native') {
      const { sharkBackend } = await import('../lib/sharkBackend');
      const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const result = await sharkBackend.search('(?i)' + escaped, 200);
      return result.hits.map(h => ({ path: h.path, line: h.line, text: h.text }));
    }
    const lower = needle.toLowerCase(); const hits: SearchHit[] = [];
    const files: Record<string, string> = kind === 'browser' ? browserFiles() : Object.fromEntries(get().tabs.map(t => [t.path, t.content]));
    for (const [path, content] of Object.entries(files)) {
      const lines = content.split('\n');
      for (let i = 0; i < lines.length && hits.length < 300; i++) if (lines[i].toLowerCase().includes(lower)) hits.push({ path, line: i + 1, text: lines[i].trim().slice(0, 240) });
    }
    return hits;
  },
}));
