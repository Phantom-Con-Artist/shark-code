import { useEffect, useRef, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { ArrowLeft, ArrowRight, Code2, Workflow, Copy, Minus, PanelBottom, PanelLeft, PanelRight, Search, Square, X } from 'lucide-react';
import { useProjectStore } from '../../stores/useProjectStore';
import { useSettings } from '../../stores/useSettings';
import { useUi } from '../../stores/useUi';
import { SharkMark } from './primitives';

export type MenuItem = { label: string; keys?: string; run(): void; disabled?: boolean } | 'separator';
export type Menu = { label: string; items: MenuItem[] };

async function win() { const { getCurrentWindow } = await import('@tauri-apps/api/window'); return getCurrentWindow(); }

function MenuBar({ menus }: { menus: Menu[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open === null) return;
    const down = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(null); };
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(null); return; }
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); setOpen(o => ((o ?? 0) + (e.key === 'ArrowRight' ? 1 : -1) + menus.length) % menus.length); }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const items = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>('.menu-dropdown button:not(:disabled)') ?? []);
        const i = items.indexOf(document.activeElement as HTMLButtonElement);
        items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
      }
    };
    document.addEventListener('pointerdown', down); document.addEventListener('keydown', key);
    return () => { document.removeEventListener('pointerdown', down); document.removeEventListener('keydown', key); };
  }, [open, menus.length]);

  return <div className="menubar" ref={ref} role="menubar">
    {menus.map((menu, i) => <div key={menu.label} className="menu-root">
      <button role="menuitem" aria-haspopup="menu" aria-expanded={open === i} className={open === i ? 'open' : ''}
        onClick={() => setOpen(open === i ? null : i)} onPointerEnter={() => { if (open !== null) setOpen(i); }}>{menu.label}</button>
      {open === i && <div className="menu-dropdown" role="menu">
        {menu.items.map((item, k) => item === 'separator' ? <hr key={k} /> :
          <button key={item.label} role="menuitem" disabled={item.disabled} onClick={() => { setOpen(null); item.run(); }}>
            <span>{item.label}</span>{item.keys && <kbd>{item.keys}</kbd>}
          </button>)}
      </div>}
    </div>)}
  </div>;
}

export function TitleBar({ menus }: { menus: Menu[] }) {
  const s = useSettings();
  const ui = useUi();
  const project = useProjectStore();
  const [maximized, setMaximized] = useState(false);
  const native = isTauri();
  const mod = /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl';

  useEffect(() => {
    if (!native) return;
    let unlisten: (() => void) | undefined;
    void win().then(async w => { setMaximized(await w.isMaximized()); unlisten = await w.onResized(async () => setMaximized(await w.isMaximized())); });
    return () => unlisten?.();
  }, [native]);

  return <header className="titlebar" data-tauri-drag-region>
    <div className="title-left" data-tauri-drag-region>
      <SharkMark />
      <MenuBar menus={menus} />
      <div className="nav-arrows">
        <button className="icon-btn sm" aria-label="Go back" title="Back · Alt ←" disabled={project.historyIndex <= 0} onClick={() => void project.navigate(-1)}><ArrowLeft size={14} /></button>
        <button className="icon-btn sm" aria-label="Go forward" title="Forward · Alt →" disabled={project.historyIndex >= project.history.length - 1} onClick={() => void project.navigate(1)}><ArrowRight size={14} /></button>
      </div>
    </div>
    <button className="omni" onClick={() => ui.open('palette')}><Search size={13} /><span className="ellipsis">{project.name}</span><kbd>{mod} K</kbd></button>
    <div className="title-actions" data-tauri-drag-region>
      <div className="view-switch" role="group" aria-label="View">
        <button aria-pressed={s.view === 'shark'} title={`Shark view: conversation first · ${mod} ⇧ M`} onClick={() => s.set({ view: 'shark' })}><SharkMark className="view-mark" />Shark</button>
        <button aria-pressed={s.view === 'code'} title={`Code view: editor first, Shark docked · ${mod} ⇧ M`} onClick={() => s.set({ view: 'code', editorOpen: true })}><Code2 size={13} />Code</button>
        <button aria-pressed={s.view === 'automata'} title="Automata: visual workflows built with Shark" onClick={() => s.set({ view: 'automata', editorOpen: true })}><Workflow size={13} />Automata</button>
      </div>
      <button className="icon-btn" aria-pressed={s.sidebarOpen} aria-label="Toggle sidebar" title={`Sidebar · ${mod} B`} onClick={() => s.toggle('sidebarOpen')}><PanelLeft size={15} /></button>
      <button className="icon-btn" aria-pressed={s.terminalOpen} aria-label="Toggle panel" title={`Panel · ${mod} J`} onClick={() => s.toggle('terminalOpen')}><PanelBottom size={15} /></button>
      <button className="icon-btn" aria-pressed={s.editorOpen} aria-label={s.view !== 'shark' ? 'Toggle Shark panel' : 'Toggle editor pane'} title={`${s.view !== 'shark' ? 'Shark panel' : 'Editor'} · ${mod} \\`} onClick={() => s.toggle('editorOpen')}><PanelRight size={15} /></button>
      {native && <div className="window-controls">
        <button aria-label="Minimize" title="Minimize" onClick={() => void win().then(w => w.minimize())}><Minus size={15} /></button>
        <button aria-label={maximized ? 'Restore' : 'Maximize'} title={maximized ? 'Restore' : 'Maximize'} onClick={() => void win().then(w => w.toggleMaximize())}>{maximized ? <Copy size={12} style={{ transform: 'scaleX(-1)' }} /> : <Square size={12} />}</button>
        <button className="close" aria-label="Close window" title="Close" onClick={() => void win().then(w => w.close())}><X size={16} /></button>
      </div>}
    </div>
  </header>;
}
