import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { FileCode2, FileImage, FileJson, FileText, FileAudio, FileVideo, BookOpen, File as FileGeneric, Settings as Cog } from 'lucide-react';

/** Shark Code mark (from assets/shark-code-black.png), drawn in the current text colour. */
export function SharkMark({ className = 'brand-mark' }: { className?: string }) {
  return <span className={`shark-mark ${className}`} aria-hidden="true" />;
}

const ICONS: Record<string, [typeof FileGeneric, string]> = {
  ts: [FileCode2, 'ts'], tsx: [FileCode2, 'ts'], mts: [FileCode2, 'ts'], js: [FileCode2, 'js'], jsx: [FileCode2, 'js'], mjs: [FileCode2, 'js'], cjs: [FileCode2, 'js'],
  css: [FileCode2, 'css'], scss: [FileCode2, 'css'], less: [FileCode2, 'css'], html: [FileCode2, 'html'], vue: [FileCode2, 'html'], svelte: [FileCode2, 'html'],
  json: [FileJson, 'json'], lock: [FileJson, 'cfg'], toml: [Cog, 'cfg'], yaml: [Cog, 'cfg'], yml: [Cog, 'cfg'], ini: [Cog, 'cfg'], env: [Cog, 'cfg'],
  rs: [FileCode2, 'rs'], py: [FileCode2, 'py'], go: [FileCode2, 'py'], java: [FileCode2, 'rs'], kt: [FileCode2, 'rs'], swift: [FileCode2, 'rs'], c: [FileCode2, 'ts'], cpp: [FileCode2, 'ts'], h: [FileCode2, 'ts'], sh: [FileCode2, 'cfg'],
  md: [FileText, 'md'], mdx: [FileText, 'md'], txt: [FileText, 'md'],
  png: [FileImage, 'img'], jpg: [FileImage, 'img'], jpeg: [FileImage, 'img'], gif: [FileImage, 'img'], svg: [FileImage, 'img'], webp: [FileImage, 'img'], ico: [FileImage, 'img'],
  avif: [FileImage, 'img'], bmp: [FileImage, 'img'],
  mp4: [FileVideo, 'img'], webm: [FileVideo, 'img'], mov: [FileVideo, 'img'], mkv: [FileVideo, 'img'], ogv: [FileVideo, 'img'], m4v: [FileVideo, 'img'],
  mp3: [FileAudio, 'img'], wav: [FileAudio, 'img'], ogg: [FileAudio, 'img'], flac: [FileAudio, 'img'], m4a: [FileAudio, 'img'], aac: [FileAudio, 'img'], opus: [FileAudio, 'img'], oga: [FileAudio, 'img'],
  ipynb: [BookOpen, 'py'],
};
export function FileIcon({ path, size = 14 }: { path: string; size?: number }) {
  const ext = path.split('/').pop()!.split('.').pop()!.toLowerCase();
  const [Icon, tone] = ICONS[ext] ?? [FileGeneric, ''];
  return <Icon size={size} className={`ficon ${tone}`} aria-hidden="true" />;
}

export const LANGUAGE: Record<string, [string, string]> = {
  ts: ['typescript', 'TypeScript'], tsx: ['typescript', 'TypeScript React'], mts: ['typescript', 'TypeScript'], js: ['javascript', 'JavaScript'], jsx: ['javascript', 'JavaScript React'], mjs: ['javascript', 'JavaScript'], cjs: ['javascript', 'JavaScript'],
  json: ['json', 'JSON'], css: ['css', 'CSS'], scss: ['scss', 'SCSS'], less: ['less', 'Less'], html: ['html', 'HTML'], md: ['markdown', 'Markdown'], mdx: ['markdown', 'MDX'],
  ipynb: ['json', 'Jupyter Notebook'],
  rs: ['rust', 'Rust'], py: ['python', 'Python'], go: ['go', 'Go'], toml: ['ini', 'TOML'], ini: ['ini', 'INI'], yaml: ['yaml', 'YAML'], yml: ['yaml', 'YAML'], sh: ['shell', 'Shell'], bash: ['shell', 'Shell'],
  java: ['java', 'Java'], kt: ['kotlin', 'Kotlin'], swift: ['swift', 'Swift'], c: ['cpp', 'C'], h: ['cpp', 'C'], cpp: ['cpp', 'C++'], sql: ['sql', 'SQL'], xml: ['xml', 'XML'], svg: ['xml', 'SVG'], dockerfile: ['dockerfile', 'Dockerfile'],
};
export function languageOf(path: string): [string, string] {
  const name = path.split('/').pop()!.toLowerCase();
  if (name === 'dockerfile') return LANGUAGE.dockerfile;
  return LANGUAGE[name.split('.').pop()!] ?? ['plaintext', 'Plain text'];
}

/** Drag/keyboard resizable hairline between panes. */
export function Splitter({ axis, value, min, max, onChange, onReset, invert = false, label }: {
  axis: 'x' | 'y'; value: number; min: number; max: number; onChange(v: number): void; onReset(): void; invert?: boolean; label: string;
}) {
  const [dragging, setDragging] = useState(false);
  const clamp = (v: number) => Math.round(Math.min(Math.max(v, min), Math.max(min, max)));
  return <div
    className={`splitter ${axis} ${dragging ? 'dragging' : ''}`} role="separator" tabIndex={0}
    aria-orientation={axis === 'x' ? 'vertical' : 'horizontal'} aria-label={label}
    aria-valuenow={value} aria-valuemin={min} aria-valuemax={max}
    onDoubleClick={onReset}
    onKeyDown={e => {
      const step = e.shiftKey ? 48 : 16;
      const grow = axis === 'x' ? (invert ? 'ArrowLeft' : 'ArrowRight') : (invert ? 'ArrowUp' : 'ArrowDown');
      const shrink = axis === 'x' ? (invert ? 'ArrowRight' : 'ArrowLeft') : (invert ? 'ArrowDown' : 'ArrowUp');
      if (e.key === grow) { e.preventDefault(); onChange(clamp(value + step)); }
      if (e.key === shrink) { e.preventDefault(); onChange(clamp(value - step)); }
      if (e.key === 'Enter') onReset();
    }}
    onPointerDown={e => {
      if (e.button !== 0) return;
      e.preventDefault();
      const start = axis === 'x' ? e.clientX : e.clientY, initial = value;
      const target = e.currentTarget; target.setPointerCapture(e.pointerId);
      setDragging(true); document.body.classList.add(`resizing-${axis}`);
      let frame = 0;
      const move = (ev: PointerEvent) => {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          const delta = (axis === 'x' ? ev.clientX : ev.clientY) - start;
          onChange(clamp(initial + (invert ? -delta : delta)));
        });
      };
      const up = () => {
        cancelAnimationFrame(frame); setDragging(false); document.body.classList.remove(`resizing-${axis}`);
        target.removeEventListener('pointermove', move); target.removeEventListener('pointerup', up); target.removeEventListener('pointercancel', up);
      };
      target.addEventListener('pointermove', move); target.addEventListener('pointerup', up); target.addEventListener('pointercancel', up);
    }}
  />;
}

/** Trap Tab within a container while active; restore focus on close. */
export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean) {
  useEffect(() => {
    const node = ref.current; if (!active || !node) return;
    const previous = document.activeElement as HTMLElement | null;
    const items = () => Array.from(node.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea, select, [tabindex="0"]'));
    if (!node.contains(document.activeElement)) (node.querySelector<HTMLElement>('[autofocus], input') ?? items()[0])?.focus();
    const trap = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const list = items(), first = list[0], last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    node.addEventListener('keydown', trap);
    return () => { node.removeEventListener('keydown', trap); previous?.focus?.(); };
  }, [active, ref]);
}

/** Anchored popover that closes on outside click / Escape. */
export function Popover({ open, onClose, children, className = '', style }: { open: boolean; onClose(): void; children: ReactNode; className?: string; style?: React.CSSProperties }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => { if (ref.current && !ref.current.contains(e.target as Node) && !(e.target as HTMLElement).closest('[data-popover-anchor]')) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } };
    document.addEventListener('pointerdown', down); document.addEventListener('keydown', key, true);
    return () => { document.removeEventListener('pointerdown', down); document.removeEventListener('keydown', key, true); };
  }, [open, onClose]);
  if (!open) return null;
  return <div ref={ref} className={`popover ${className}`} style={style} role="dialog">{children}</div>;
}

export function relativeTime(seconds: number) {
  const diff = Date.now() / 1000 - seconds;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function changeKind(f: { before_version: string | null; after_version: string | null }) {
  return f.before_version === null ? 'create' : f.after_version === null ? 'delete' : 'edit';
}
