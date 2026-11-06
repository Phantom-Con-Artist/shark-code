import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useDialogs, settleDialog } from '../../stores/useDialogs';
import { useFocusTrap } from './primitives';

export function AppDialogs() {
  const active = useDialogs(s => s.active);
  return active ? createPortal(<DialogBody key={active.id} />, document.body) : null;
}
function DialogBody() {
  const dialog = useDialogs(s => s.active)!;
  const [value, setValue] = useState(dialog.input?.value ?? '');
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, true);
  return <div className="scrim app-dialog-scrim" onPointerDown={e => {if (e.target === e.currentTarget) settleDialog(null);}} onKeyDown={e => {e.stopPropagation(); if (e.key === 'Escape') {e.preventDefault(); settleDialog(null);}}}>
    <div className="dialog app-dialog" role={dialog.danger ? 'alertdialog' : 'dialog'} aria-modal="true" aria-labelledby="app-dialog-title" aria-describedby="app-dialog-message" ref={ref}>
      <form onSubmit={e => {e.preventDefault(); if (!dialog.input || value.trim()) settleDialog(dialog.input ? value.trim() : 'confirmed');}}>
        <h2 id="app-dialog-title">{dialog.title}</h2>
        <p id="app-dialog-message">{dialog.message}</p>
        {dialog.input && <label>{dialog.input.label}<input className="field" autoFocus value={value} onChange={e => setValue(e.target.value)} onFocus={e => e.target.select()} /></label>}
        <footer><button className="btn" type="button" autoFocus={dialog.danger && !dialog.input} onClick={() => settleDialog(null)}>Cancel</button><button className={`btn ${dialog.danger ? 'danger-action' : 'primary'}`} type="submit" disabled={!!dialog.input && !value.trim()} autoFocus={!dialog.danger && !dialog.input}>{dialog.confirmLabel ?? 'Continue'}</button></footer>
      </form>
    </div>
  </div>;
}
