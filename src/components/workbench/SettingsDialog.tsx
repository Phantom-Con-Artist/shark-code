import { Select } from './NativeUi';
import { useRef, useState } from 'react';
import { Bot, Code2, Keyboard, Laptop, Moon, Palette, Plus, Sparkles, Sun, Trash2, X } from 'lucide-react';
import { useAgentWorkspace } from '../../stores/useAgentWorkspace';
import { useProjectStore } from '../../stores/useProjectStore';
import { API_ORDER, BUILTIN_SKILLS, CLI_ORDER, LAYOUT_DEFAULTS, PROVIDERS, useSettings, type ProviderId } from '../../stores/useSettings';
import { useUi } from '../../stores/useUi';
import { readiness } from './AgentPanel';
import { useFocusTrap } from './primitives';

const SECTIONS = [
  { id: 'appearance', label: 'Appearance', icon: Palette },
  { id: 'agents', label: 'Shark engine', icon: Bot },
  { id: 'skills', label: 'Skills', icon: Sparkles },
  { id: 'editor', label: 'Editor', icon: Code2 },
  { id: 'keys', label: 'Shortcuts', icon: Keyboard },
] as const;

function Toggle({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange(v: boolean): void }) {
  return <label className="setting"><span className="text"><span>{label}</span>{hint && <small>{hint}</small>}</span><input type="checkbox" className="switch" checked={checked} onChange={e => onChange(e.target.checked)} /></label>;
}
function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <div className="setting"><span className="text"><span>{label}</span>{hint && <small>{hint}</small>}</span>{children}</div>;
}

export function SettingsDialog() {
  const section = useUi(u => u.settingsSection);
  const ui = useUi();
  const s = useSettings();
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, true);
  const close = () => ui.open(null);

  return <div className="scrim" onPointerDown={e => { if (e.target === e.currentTarget) close(); }} onKeyDown={e => { if (e.key === 'Escape') close(); }}>
    <div className="dialog settings" ref={ref} role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <nav aria-label="Settings sections">
        <h2 id="settings-title">Settings</h2>
        {SECTIONS.map(({ id, label, icon: Icon }) => <button key={id} aria-pressed={section === id} onClick={() => ui.set({ settingsSection: id })}><Icon size={15} />{label}</button>)}
      </nav>
      <div className="settings-body">
        <button className="icon-btn settings-close" aria-label="Close settings" onClick={close}><X size={16} /></button>
        {section === 'appearance' && <>
          <h3>Appearance</h3>
          <p>Theme, density and layout. Saved on this device.</p>
          <Row label="Theme">
            <div className="segmented" role="group" aria-label="Theme">
              {([['system', Laptop, 'System'], ['light', Sun, 'Light'], ['dark', Moon, 'Dark']] as const).map(([v, Icon, l]) =>
                <button key={v} aria-pressed={s.theme === v} onClick={() => s.set({ theme: v })}><Icon size={13} />{l}</button>)}
            </div>
          </Row>
          <Row label="Density" hint="Compact fits more; comfortable adds breathing room.">
            <div className="segmented" role="group" aria-label="Density">
              <button aria-pressed={s.density === 'compact'} onClick={() => s.set({ density: 'compact' })}>Compact</button>
              <button aria-pressed={s.density === 'comfortable'} onClick={() => s.set({ density: 'comfortable' })}>Comfortable</button>
            </div>
          </Row>
          <Row label="Interface text size">
            <Select label="Interface text size" value={s.fontSize} onChange={v => s.set({ fontSize: v })} options={[12, 13, 14, 15, 17].map(n => ({ value: n, label: `${n}px${n === 13 ? ' (default)' : ''}` }))} />
          </Row>
          <Row label="Pane sizes" hint="Drag any divider to resize. Double-click a divider to reset it.">
            <button className="btn sm" onClick={() => s.set({ ...LAYOUT_DEFAULTS, sidebarOpen: true })}>Reset layout</button>
          </Row>
          <Toggle label="Readable font" hint="Use Verdana for interface text." checked={s.readingFont === 'readable'} onChange={v => s.set({ readingFont: v ? 'readable' : 'default' })} />
          <Toggle label="Higher contrast" hint="Stronger text and borders." checked={s.highContrast} onChange={v => s.set({ highContrast: v })} />
          <Toggle label="Reduce motion" hint="Turn off transitions and blinking cursors." checked={s.reduceMotion} onChange={v => s.set({ reduceMotion: v })} />
        </>}
        {section === 'agents' && <AgentsSection />}
        {section === 'skills' && <SkillsSection />}
        {section === 'editor' && <>
          <h3>Editor</h3>
          <p>Applies to the code editor, diffs and terminal.</p>
          <Row label="Font size">
            <Select label="Editor text size" value={s.editorFontSize} onChange={v => s.set({ editorFontSize: v })} options={[12, 13, 14, 15, 16, 18].map(n => ({ value: n, label: `${n}px` }))} />
          </Row>
          <Toggle label="Word wrap" checked={s.wordWrap} onChange={v => s.set({ wordWrap: v })} />
          <Toggle label="Minimap" checked={s.minimap} onChange={v => s.set({ minimap: v })} />
        </>}
        {section === 'keys' && <>
          <h3>Keyboard shortcuts</h3>
          <p>Ctrl on Windows and Linux, ⌘ on macOS.</p>
          <div className="keys-table">
            {[['Command palette', 'Ctrl K'], ['Go to file', 'Ctrl P'], ['Ask the agent', 'Ctrl L'], ['New chat', 'Ctrl N'], ['Save file', 'Ctrl S'], ['Close tab', 'Ctrl W'],
              ['Toggle sidebar', 'Ctrl B'], ['Toggle editor pane', 'Ctrl \\'], ['Toggle panel', 'Ctrl J'], ['Run build task', 'Ctrl Shift B'], ['Back / forward', 'Alt ← / →'], ['Next / previous tab', 'Ctrl Tab'], ['Markdown preview', 'Ctrl Shift V'], ['Search in files', 'Ctrl Shift F'], ['Settings', 'Ctrl ,'],
              ['Move focus out of the editor', 'Ctrl M, then Tab']].map(([l, k]) => <span key={l} style={{ display: 'contents' }}><span>{l}</span><kbd>{k}</kbd></span>)}
          </div>
        </>}
      </div>
    </div>
  </div>;
}

function AgentsSection() {
  const s = useSettings();
  const agent = useAgentWorkspace();
  const native = useProjectStore(p => p.kind) === 'native';
  const [shown, setShown] = useState<Partial<Record<ProviderId, boolean>>>({});
  return <>
    <h3>Shark engine</h3>
    <p>Shark is one agent. Pick what powers it: a coding CLI you are already signed in to, or your own API key. Every engine works the same way: runs stream into the conversation and edits come back as a review.</p>
    {([['CLI engines', 'Sign in with each tool\'s own command first. Shark runs it in an isolated copy and turns its edits into a review.', CLI_ORDER], ['API keys', 'Bring your own key. Shark explores with workspace tools and proposes edits.', API_ORDER]] as const).map(([title, blurb, ids]) => <div key={title} className="provider-group"><h4 className="label">{title}</h4><p className="fine" style={{ margin: '2px 0 10px' }}>{blurb}</p>{ids.map(id => {
      const meta = PROVIDERS[id], r = readiness(id, native, agent.providers, s.keys);
      return <section key={id} className={`provider-card ${s.provider === id ? 'selected' : ''}`}>
        <header>
          <span className="text"><strong>{meta.label}</strong><small>{meta.kind === 'cli' ? (agent.providers.find(p => p.id === id)?.reason ?? meta.hint) : `API key from ${meta.keyUrl}`}</small></span>
          <span className="state"><span className={`dot ${r.tone}`} />{r.label}</span>
          <button className={`btn sm ${s.provider === id ? 'primary' : ''}`} onClick={() => s.set({ provider: id })} aria-pressed={s.provider === id}>{s.provider === id ? 'Default' : 'Use'}</button>
        </header>
        {<div className="row" style={meta.kind === 'cli' ? { gridTemplateColumns: '1fr' } : undefined}>
          {meta.kind === 'byok' && <label>API key
            <span className="key-input">
              <input className="field" type={shown[id] ? 'text' : 'password'} value={s.keys[id] ?? ''} autoComplete="off" spellCheck={false}
                placeholder={r.label === 'From environment' ? `Using ${meta.keyEnv} from environment` : 'Paste key'}
                onChange={e => s.set({ keys: { ...s.keys, [id]: e.target.value.trim() || undefined } })} />
              <button className="btn sm ghost" type="button" onClick={() => setShown(v => ({ ...v, [id]: !v[id] }))}>{shown[id] ? 'Hide' : 'Show'}</button>
            </span>
          </label>}
          <label>Model
            <input className="field" list={`models-${id}`} value={s.models[id]} spellCheck={false} placeholder={meta.kind === 'cli' ? 'CLI default' : 'Model ID'}
              onChange={e => s.set({ models: { ...s.models, [id]: e.target.value } })} />
            <datalist id={`models-${id}`}>{meta.models.filter(Boolean).map(m => <option key={m} value={m} />)}</datalist>
          </label>
        </div>}
        {meta.kind === 'cli' && r.label === 'Not installed' && <p className="fine">Install the {meta.label} CLI and sign in from a terminal, then reopen this project.</p>}
      </section>;
    })}</div>)}
    <p className="fine">Keys are saved in this app's local storage on this device and sent only to the local Shark backend when a run starts. They are never written to task history. Leave a key empty to use <code>ANTHROPIC_API_KEY</code> / <code>GEMINI_API_KEY</code> from the backend environment.</p>
  </>;
}

function SkillsSection() {
  const s = useSettings();
  const [name, setName] = useState('');
  const [text, setText] = useState('');
  const toggle = (id: string) => s.set({ skills: s.skills.includes(id) ? s.skills.filter(x => x !== id) : [...s.skills, id] });
  return <>
    <h3>Skills</h3>
    <p>Skills shape how Shark works and talks, on every engine. They stack with the current mode and stay with this profile.</p>
    {BUILTIN_SKILLS.map(k => <label key={k.id} className="setting"><span className="text"><span>{k.label}</span><small>{k.hint}</small></span><input type="checkbox" className="switch" checked={s.skills.includes(k.id)} onChange={() => toggle(k.id)} /></label>)}
    {s.customSkills.map(c => <div key={c.id} className="setting"><span className="text"><span>{c.name}</span><small>{c.text}</small></span>
      <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input type="checkbox" className="switch" aria-label={`Use ${c.name}`} checked={s.activeCustomSkills.includes(c.id)} onChange={e => s.set({ activeCustomSkills: e.target.checked ? [...s.activeCustomSkills, c.id] : s.activeCustomSkills.filter(x => x !== c.id) })} />
        <button className="icon-btn sm" aria-label={`Delete ${c.name}`} onClick={() => s.set({ customSkills: s.customSkills.filter(x => x.id !== c.id), activeCustomSkills: s.activeCustomSkills.filter(x => x !== c.id) })}><Trash2 size={13} /></button>
      </span></div>)}
    <form className="provider-card" style={{ marginTop: 14 }} onSubmit={e => { e.preventDefault(); if (!name.trim() || !text.trim() || s.customSkills.length >= 5) return; const id = Math.random().toString(36).slice(2, 9); s.set({ customSkills: [...s.customSkills, { id, name: name.trim().slice(0, 40), text: text.trim().slice(0, 600) }], activeCustomSkills: [...s.activeCustomSkills, id] }); setName(''); setText(''); }}>
      <strong>New skill</strong>
      <label>Name<input className="field" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Pirate, Strict typing, Explain Big-O" /></label>
      <label>Instructions<textarea className="field" rows={3} style={{ height: 'auto', padding: '8px 10px' }} value={text} onChange={e => setText(e.target.value)} placeholder="How Shark should behave, in one or two sentences." /></label>
      <button className="btn sm primary" disabled={!name.trim() || !text.trim() || s.customSkills.length >= 5} style={{ alignSelf: 'flex-start' }}><Plus size={12} />Add skill</button>
      <p className="fine">Up to five custom skills, 600 characters each.</p>
    </form>
  </>;
}
