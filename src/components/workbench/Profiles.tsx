import { confirmAction } from '../../stores/useDialogs';
import { useState } from 'react';
import { Check, Pencil, Plus, Trash2 } from 'lucide-react';
import { useProfiles } from '../../stores/useProfiles';

/** Profile manager: each profile keeps its own settings, layout, agent choice and API keys. */
export function ProfileMenu({ onDone }: { onDone(): void }) {
  const p = useProfiles();
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [adding, setAdding] = useState(false);
  return <div className="profiles">
    <div className="group label">Profiles</div>
    {p.profiles.map(profile => <div key={profile.id} className="profile-row">
      {editing === profile.id
        ? <form className="grow" onSubmit={e => { e.preventDefault(); p.rename(profile.id, name); setEditing(null); }}><input className="field" autoFocus value={name} onChange={e => setName(e.target.value)} onBlur={() => setEditing(null)} aria-label="Profile name" /></form>
        : <button className="menu-item" aria-checked={p.active === profile.id} onClick={() => { if (p.active !== profile.id) p.switchTo(profile.id); else onDone(); }}>
          <span className="avatar" style={{ background: profile.color }}>{profile.name.slice(0, 1).toUpperCase()}</span>
          <span className="text"><span>{profile.name}</span><small>{p.active === profile.id ? 'Active' : 'Switch (reloads)'}</small></span>
          {p.active === profile.id && <Check size={14} />}
        </button>}
      {editing !== profile.id && <button className="icon-btn sm" aria-label={`Rename ${profile.name}`} onClick={() => { setName(profile.name); setEditing(profile.id); }}><Pencil size={12} /></button>}
      {profile.id !== 'default' && editing !== profile.id && <button className="icon-btn sm" aria-label={`Delete ${profile.name}`} onClick={async () => { if (await confirmAction({title: 'Delete profile?', message: `Remove “${profile.name}” and its settings and keys?`, confirmLabel: 'Delete profile', danger: true})) p.remove(profile.id); }}><Trash2 size={12} /></button>}
    </div>)}
    <hr />
    {adding
      ? <form className="model-field" onSubmit={e => { e.preventDefault(); const id = p.create(name); setAdding(false); setName(''); p.switchTo(id); }}>
          <input className="field" autoFocus placeholder="Profile name, e.g. Work" value={name} onChange={e => setName(e.target.value)} aria-label="New profile name" />
          <p className="fine">Starts clean: its own theme, layout, agents and keys.</p>
        </form>
      : <button className="menu-item" onClick={() => { setName(''); setAdding(true); }}><Plus size={14} /><span className="text">New profile</span></button>}
  </div>;
}
