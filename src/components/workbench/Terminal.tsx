import { useEffect, useRef } from 'react';
import { Channel, invoke, isTauri } from '@tauri-apps/api/core';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { useSettings } from '../../stores/useSettings';
import { useUi } from '../../stores/useUi';

const THEMES = {
  dark: { background: '#15171b', foreground: '#d9dde4', cursor: '#7cc4f0', cursorAccent: '#15171b', selectionBackground: '#2a4560', black: '#1d2025', brightBlack: '#5d636e', blue: '#7cc4f0', green: '#a8d4a0', yellow: '#e8c98a', red: '#ef8f88', magenta: '#c4a7f5', cyan: '#7dd3d8' },
  light: { background: '#fcfcfd', foreground: '#262a31', cursor: '#2563eb', cursorAccent: '#fcfcfd', selectionBackground: '#cfe2f7', black: '#262a31', brightBlack: '#8a919c', blue: '#1d4ed8', green: '#2f7d32', yellow: '#a16207', red: '#c2410c', magenta: '#7c3aed', cyan: '#0e7490' },
};
import { useProjectStore } from '../../stores/useProjectStore';
import { useTerminals } from '../../stores/useTerminals';

type Session = { term: Terminal; send: ((command: string) => void) | null; queue: string[] };
const sessions = new Map<string, Session>();
const sessionFor = (id: string): Session => { let s = sessions.get(id); if (!s) { s = { term: null as unknown as Terminal, send: null, queue: [] }; sessions.set(id, s); } return s; };

/** Run a command in a workspace shell tab (opens once the shell is ready). Defaults to the active tab, creating one if none exists. */
export function runInTerminal(command: string, sessionId?: string) {
  const id = sessionId ?? useTerminals.getState().ensureActive();
  const s = sessionFor(id);
  if (s.send) s.send(command); else s.queue.push(command);
}
export function clearTerminal(sessionId?: string) {
  const id = sessionId ?? useTerminals.getState().activeId;
  sessions.get(id)?.term?.clear();
}

export function WorkspaceTerminal({ sessionId }: { sessionId: string }) {
  const container = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);
  const prefs = useSettings();
  const theme = useUi(u => u.resolvedTheme);
  const root = useProjectStore(s => s.root);
  useEffect(() => {
    if (!container.current) return;
    let disposed = false; let nativeId: number | null = null;
    const term = new Terminal({ fontSize: prefs.editorFontSize, lineHeight: 1.35, screenReaderMode: true, cursorBlink: !prefs.reduceMotion, cursorStyle: 'bar', fontFamily: "'Geist Mono Variable', ui-monospace, monospace", convertEol: true, theme: THEMES[useUi.getState().resolvedTheme], allowTransparency: true });
    const fit = new FitAddon(); term.loadAddon(fit); term.open(container.current); terminal.current = term;
    const session = sessionFor(sessionId); session.term = term;
    let line = ''; let cwd = ''; let busy = false; const history: string[] = []; let historyIndex = 0;
    const prompt = () => term.write(`\x1b[34m${useProjectStore.getState().name}\x1b[0m ${cwd || '/'} $ `);
    const resolvePath = (path: string) => { const parts = (path.startsWith('/') ? path.slice(1) : [cwd, path].filter(Boolean).join('/')).split('/'); const clean: string[] = []; for (const part of parts) { if (part === '..') clean.pop(); else if (part && part !== '.') clean.push(part); } return clean.join('/'); };
    const execute = async (command: string) => {
      const [name, ...args] = command.trim().split(/\s+/); const state = useProjectStore.getState();
      if (!name) return;
      if (name === 'help') term.writeln('Browser workspace commands: help, pwd, ls [folder], cd <folder>, cat <file>, touch <file>, clear.\r\nFor npm, git, and an interactive system shell, run the Tauri desktop app.');
      else if (name === 'clear') term.clear();
      else if (name === 'pwd') term.writeln('/' + cwd);
      else if (name === 'ls') { const path = resolvePath(args[0] || '.'); const entries = state.entries.filter(e => e.path.split('/').slice(0,-1).join('/') === path); term.writeln(entries.map(e => e.path.split('/').pop() + (e.directory ? '/' : '')).join('  ') || '(empty)'); }
      else if (name === 'cd') { const path = resolvePath(args[0] || '/'); if (!path || state.entries.some(e => e.path === path && e.directory)) cwd = path; else term.writeln('Folder not found.'); }
      else if (name === 'cat') { if (!args[0]) { term.writeln('Usage: cat <file>'); return; } const path = resolvePath(args[0]); await state.openFile(path); const file = useProjectStore.getState().tabs.find(t => t.path === path); term.writeln(file ? file.saved : useProjectStore.getState().error); }
      else if (name === 'touch') { if (!args[0]) { term.writeln('Usage: touch <file>'); return; } await state.createFile(resolvePath(args[0])); term.writeln(useProjectStore.getState().error || 'File created.'); }
      else term.writeln(`\x1b[33m${name}: requires the desktop shell.\x1b[0m Type help for available browser commands.`);
    };
    const data = term.onData(async data => {
      if (isTauri()) { if (nativeId !== null) void invoke('terminal_write', { id: nativeId, data }).catch(e => term.writeln(`\r\n${e}`)); return; }
      if (busy) return;
      if (data === '\x1b[A' || data === '\x1b[B') { historyIndex = Math.max(0, Math.min(history.length, historyIndex + (data === '\x1b[A' ? -1 : 1))); term.write('\r\x1b[2K'); prompt(); line = history[historyIndex] || ''; term.write(line); return; }
      for (const char of data) {
        if (char === '\r' || char === '\n') { term.writeln(''); const command = line; line = ''; if (command.trim()) history.push(command); historyIndex = history.length; busy = true; try { await execute(command); } catch (e) { term.writeln(String(e)); } finally { busy = false; if (!disposed) prompt(); } }
        else if (char === '\x03') { line = ''; term.writeln('^C'); prompt(); }
        else if (char === '\x7f') { if (line.length) { line = line.slice(0,-1); term.write('\b \b'); } }
        else if (char >= ' ') { line += char; term.write(char); }
      }
    });
    const resize = () => { if (disposed || !container.current?.clientWidth) return; fit.fit(); if (nativeId !== null) void invoke('terminal_resize', { id: nativeId, cols: term.cols, rows: term.rows }).catch(() => {}); };
    const observer = new ResizeObserver(resize); observer.observe(container.current); resize();
    const start = async () => {
      if (isTauri()) {
        try { await useProjectStore.getState().initialize(); const output = new Channel<number[]>(); output.onmessage = bytes => { if (!disposed) term.write(new Uint8Array(bytes)); }; const id = await invoke<number>('terminal_open', { output }); if (disposed) { await invoke('terminal_close', { id }); return; } nativeId = id; resize(); session.send = command => void invoke('terminal_write', { id, data: command + '\r' }); session.queue.splice(0).forEach(c => session.send?.(c)); }
        catch (e) { if (!disposed) term.writeln(`Unable to start shell: ${e}`); }
      } else { term.writeln('\x1b[90mBrowser workspace console · type help for commands.\x1b[0m'); prompt(); session.send = command => { term.writeln(`\r\n\x1b[33m${command}\x1b[0m: build and run tasks need the desktop app.`); prompt(); }; session.queue.splice(0).forEach(c => session.send?.(c)); }
    };
    void start();
    return () => { disposed = true; sessions.delete(sessionId); observer.disconnect(); data.dispose(); if (nativeId !== null) void invoke('terminal_close', { id: nativeId }); term.dispose(); terminal.current = null; };
  }, [root, sessionId]);
  useEffect(() => { if (terminal.current) terminal.current.options.theme = THEMES[theme]; }, [theme]);
  useEffect(() => { if (terminal.current) terminal.current.options.fontSize = prefs.editorFontSize; }, [prefs.editorFontSize]);
  return <div className="terminal-surface" ref={container} />;
}
