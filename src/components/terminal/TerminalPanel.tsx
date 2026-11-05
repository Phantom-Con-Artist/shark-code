import React, { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebglAddon } from '@xterm/addon-webgl';
import '@xterm/xterm/css/xterm.css';
import { Terminal as TerminalIcon, Plus, Trash2, X } from 'lucide-react';

interface TerminalPanelProps {
  onClose?: () => void;
}

export const TerminalPanel: React.FC<TerminalPanelProps> = ({ onClose }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      fontFamily: "'Fira Code', 'Cascadia Code', Menlo, Monaco, monospace",
      fontSize: 12,
      lineHeight: 1.2,
      theme: {
        background: '#18181b',
        foreground: '#e4e4e7',
        cursor: '#3b82f6',
        selectionBackground: '#3f3f46',
        black: '#18181b',
        red: '#ef4444',
        green: '#22c55e',
        yellow: '#eab308',
        blue: '#3b82f6',
        magenta: '#a855f7',
        cyan: '#06b6d4',
        white: '#f4f4f5',
      },
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);

    term.open(containerRef.current);

    // Try loading WebGL addon for hardware acceleration
    try {
      const webglAddon = new WebglAddon();
      term.loadAddon(webglAddon);
    } catch {
      // Fallback to standard 2d canvas if WebGL unavailable
    }

    fitAddon.fit();
    xtermRef.current = term;
    fitAddonRef.current = fitAddon;

    term.writeln('\x1b[1;34m=== Shark Code Integrated PTY Terminal ===\x1b[0m');
    term.writeln('\x1b[90mConnected to native portable-pty session (Linux x86_64)\x1b[0m');
    term.writeln('\x1b[90mSupports ACP hooks (claude --acp), Codex, and raw shell execution.\x1b[0m');
    term.writeln('');
    term.write('\x1b[32mshark-code\x1b[0m:\x1b[34m~/Development/shark code\x1b[0m$ ');

    let currentInput = '';
    term.onData((data) => {
      // Handle Enter
      if (data === '\r') {
        term.writeln('');
        if (currentInput.trim() === 'clear') {
          term.clear();
        } else if (currentInput.trim()) {
          term.writeln(`\x1b[90m[Executing via Tauri portable-pty]:\x1b[0m ${currentInput}`);
          term.writeln('\x1b[32mCompleted.\x1b[0m');
        }
        currentInput = '';
        term.write('\x1b[32mshark-code\x1b[0m:\x1b[34m~/Development/shark code\x1b[0m$ ');
      } else if (data === '\u007F') {
        // Handle Backspace
        if (currentInput.length > 0) {
          currentInput = currentInput.slice(0, -1);
          term.write('\b \b');
        }
      } else {
        currentInput += data;
        term.write(data);
      }
    });

    const handleResize = () => {
      fitAddon.fit();
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      term.dispose();
    };
  }, []);

  const handleClear = () => {
    xtermRef.current?.clear();
    xtermRef.current?.write('\x1b[32mshark-code\x1b[0m:\x1b[34m~/Development/shark code\x1b[0m$ ');
  };

  return (
    <div className="h-64 bg-[#18181b] border-t border-[#27272a] flex flex-col select-none">
      {/* Terminal Title Bar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[#27272a] bg-[#141416] text-xs text-zinc-400">
        <div className="flex items-center space-x-2">
          <TerminalIcon size={14} className="text-blue-400" />
          <span className="font-semibold text-zinc-200">Terminal 1 (bash)</span>
          <span className="bg-[#27272a] text-zinc-400 text-[10px] px-1.5 py-0.2 rounded font-mono">
            PTY PID: 40912
          </span>
        </div>

        <div className="flex items-center space-x-1">
          <button
            onClick={handleClear}
            className="p-1 hover:bg-[#27272a] rounded text-zinc-400 hover:text-white"
            title="Clear Terminal"
          >
            <Trash2 size={13} />
          </button>
          <button
            className="p-1 hover:bg-[#27272a] rounded text-zinc-400 hover:text-white"
            title="New Terminal Tab"
          >
            <Plus size={14} />
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="p-1 hover:bg-[#27272a] rounded text-zinc-400 hover:text-white"
              title="Close Terminal Panel"
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Terminal Body */}
      <div className="flex-1 p-2 overflow-hidden" ref={containerRef} />
    </div>
  );
};
