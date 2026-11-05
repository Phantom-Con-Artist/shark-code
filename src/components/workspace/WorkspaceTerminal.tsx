import { useEffect, useRef, useState } from 'react';
import { Channel, invoke, isTauri } from '@tauri-apps/api/core';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { Maximize2, Minimize2, Terminal as TerminalIcon, Trash2, X } from 'lucide-react';
import '@xterm/xterm/css/xterm.css';
import { useReadingPreferences } from '../../stores/useReadingPreferences';
import { useProjectStore } from '../../stores/useProjectStore';
export function WorkspaceTerminal({ onClose }: { onClose(): void }) {
  const container = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);
  const [expanded, setExpanded] = useState(false);
  const prefs = useReadingPreferences();
  const root = useProjectStore(s => s.root);
  useEffect(() => {
    if (!container.current) return;
    let disposed = false; let nativeId: number | null = null;
    const term = new Terminal({ fontSize: prefs.fontSize, lineHeight: 1.35, screenReaderMode: true, cursorBlink: !prefs.reduceMotion, fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace', convertEol: true, theme: { background: '#151517', foreground: '#d8d8df', cursor: '#9bcbb6', selectionBackground: '#3e5a50' } });
    const fit = new FitAddon(); term.loadAddon(fit); term.open(container.current); terminal.current = term;
    let line = ''; let cwd = ''; let busy = false; const history: string[] = []; let historyIndex = 0;
    const prompt = () => term.write(`\x1b[38;2;155;203;182m${useProjectStore.getState().name}\x1b[0m ${cwd || '/'} $ `);
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
        try { await useProjectStore.getState().initialize(); const output = new Channel<number[]>(); output.onmessage = bytes => { if (!disposed) term.write(new Uint8Array(bytes)); }; const id = await invoke<number>('terminal_open', { output }); if (disposed) { await invoke('terminal_close', { id }); return; } nativeId = id; resize(); }
        catch (e) { if (!disposed) term.writeln(`Unable to start shell: ${e}`); }
      } else { term.writeln('\x1b[90mBrowser workspace console · type help for commands.\x1b[0m'); prompt(); }
    };
    void start();
    return () => { disposed = true; observer.disconnect(); data.dispose(); if (nativeId !== null) void invoke('terminal_close', { id: nativeId }); term.dispose(); terminal.current = null; };
  }, [root]);
  return <section className={`workspace-terminal ${expanded ? 'expanded' : ''}`} aria-label="Terminal"><header><div><TerminalIcon size={14}/><strong>Terminal</strong><span>{isTauri() ? 'Local shell' : 'Browser console'}</span></div><div><button className="icon-button" aria-label="Clear terminal" onClick={() => terminal.current?.clear()}><Trash2 size={13}/></button><button className="icon-button" aria-label={expanded ? 'Restore terminal size' : 'Expand terminal'} onClick={() => setExpanded(v => !v)}>{expanded ? <Minimize2 size={13}/> : <Maximize2 size={13}/>}</button><button className="icon-button" aria-label="Close terminal" onClick={onClose}><X size={14}/></button></div></header><div className="terminal-surface" ref={container}/></section>;
}
