// Shark-styled replacements for OS widgets: hover hints (from any `title`) and select menus.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';

/** Moves `title` text into a styled tip so every hover hint looks the same on every OS. Mount once. */
export function Tooltips() {
  const [tip, setTip] = useState<{ text: string; x: number; y: number; below: boolean } | null>(null);
  useEffect(() => {
    let timer: number | undefined, current: Element | null = null;
    const hide = () => { window.clearTimeout(timer); current = null; setTip(null); };
    const over = (e: PointerEvent) => {
      const el = (e.target as Element | null)?.closest?.('[title], [data-tip]');
      if (el === current) return;
      hide();
      if (!el) return;
      // An iframe's title names its document for assistive technology.
      if (el.tagName === 'IFRAME') return;
      const title = el.getAttribute('title');
      if (title) { el.setAttribute('data-tip', title); el.removeAttribute('title'); }
      const text = el.getAttribute('data-tip');
      if (!text?.trim()) return;
      current = el;
      timer = window.setTimeout(() => {
        const r = el.getBoundingClientRect();
        const below = r.top < 80;
        setTip({ text, x: Math.min(window.innerWidth - 12, Math.max(12, r.left + r.width / 2)), y: below ? r.bottom + 6 : r.top - 6, below });
      }, 450);
    };
    window.addEventListener('pointerover', over, true);
    for (const ev of ['pointerdown', 'scroll', 'keydown', 'blur'] as const) window.addEventListener(ev, hide, true);
    return () => { window.removeEventListener('pointerover', over, true); for (const ev of ['pointerdown', 'scroll', 'keydown', 'blur'] as const) window.removeEventListener(ev, hide, true); };
  }, []);
  const ref = useRef<HTMLDivElement>(null);
  const [shift, setShift] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current; if (!el || !tip) return;
    const r = el.getBoundingClientRect();
    setShift(r.right > window.innerWidth - 8 ? window.innerWidth - 8 - r.right : r.left < 8 ? 8 - r.left : 0);
  }, [tip]);
  if (!tip) return null;
  return <div ref={ref} role="tooltip" className={`shark-tip ${tip.below ? 'below' : ''}`} style={{ left: tip.x + shift, top: tip.y }}>{tip.text}</div>;
}

export type SelectOption<T extends string | number> = { value: T; label: string; detail?: string; group?: string };

/** A select menu drawn by Shark: keyboard (arrows, Enter, Esc), groups and a detail column. */
export function Select<T extends string | number>({ value, options, onChange, id, label, className = '' }:
  { value: T; options: SelectOption<T>[]; onChange(v: T): void; id?: string; label?: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const current = options.find(o => o.value === value);
  useEffect(() => {
    if (!open) return;
    setIndex(Math.max(0, options.findIndex(o => o.value === value)));
    const close = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener('pointerdown', close, true);
    return () => window.removeEventListener('pointerdown', close, true);
  }, [open, options, value]);
  const pick = (o: SelectOption<T>) => { onChange(o.value); setOpen(false); };
  const key = (e: React.KeyboardEvent) => {
    if (!open && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setOpen(true); return; }
    if (!open) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setOpen(false); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setIndex(i => Math.min(options.length - 1, i + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setIndex(i => Math.max(0, i - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(options[index]); }
  };
  let lastGroup: string | undefined;
  return <div ref={root} className={`shark-select ${className}`} onKeyDown={key}>
    <button type="button" id={id} className="field shark-select-btn" aria-haspopup="listbox" aria-expanded={open} aria-label={label} onClick={() => setOpen(o => !o)}>
      <span className="ellipsis">{current?.label ?? String(value)}</span>{current?.detail && <span className="detail">{current.detail}</span>}<ChevronDown size={12} />
    </button>
    {open && <div className="shark-select-menu" role="listbox" aria-label={label}>
      {options.map((o, i) => {
        const heading = o.group && o.group !== lastGroup ? o.group : null; lastGroup = o.group;
        return <div key={String(o.value)}>
          {heading && <div className="shark-select-group">{heading}</div>}
          <button type="button" role="option" aria-selected={o.value === value} className={`menu-item ${i === index ? 'focused' : ''}`} onMouseMove={() => setIndex(i)} onClick={() => pick(o)}>
            {o.value === value ? <Check size={12} /> : <span style={{ width: 12 }} />}<span className="ellipsis">{o.label}</span>{o.detail && <span className="detail">{o.detail}</span>}
          </button>
        </div>;
      })}
    </div>}
  </div>;
}
