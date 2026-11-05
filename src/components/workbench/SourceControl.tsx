import { useCallback, useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, Check, ChevronDown, CloudDownload, GitBranch, GitBranchPlus, GitCommitHorizontal, Minus, Plus, RefreshCw, Sparkles } from 'lucide-react';
import { Popover } from './primitives';
import { sharkGit, type GitStatus } from '../../lib/sharkBackend';
import { useProjectStore } from '../../stores/useProjectStore';
import { askAgent } from './BottomPanel';
import { useGit } from '../../stores/useGit';
import { FileIcon, relativeTime } from './primitives';
import { openPath } from './Sidebar';

const LETTER: Record<string, string> = { modified: 'M', added: 'A', deleted: 'D', renamed: 'R', untracked: 'U', conflict: '!' };

/** Native git: status, stage/unstage, commit, history. Same API agents can call. */
export function SourceControl() {
  const native = useProjectStore(s => s.kind) === 'native';
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [log, setLog] = useState<{ short: string; subject: string; time: string; author: string }[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState<'' | 'fetch' | 'pull' | 'push'>('');
  const [branchMenu, setBranchMenu] = useState(false);
  const [branches, setBranches] = useState<{ name: string; current: boolean }[]>([]);
  const [newBranch, setNewBranch] = useState('');
  const refresh = useCallback(async () => {
    if (!native) return;
    try { const st = await sharkGit.status(); setStatus(st); void useGit.getState().refresh(); if (st.repo) setLog((await sharkGit.log(15)).commits); setError(''); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, [native]);
  useEffect(() => { void refresh(); const id = setInterval(() => void refresh(), 5000); return () => clearInterval(id); }, [refresh]);
  const act = async (fn: () => Promise<unknown>) => { setBusy(true); try { await fn(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); } };

  const sync = async (action: 'fetch' | 'pull' | 'push') => {
    if (action === 'push' && !window.confirm(`Push ${status?.branch ?? 'this branch'} to its remote?`)) return;
    setSyncing(action); setError('');
    try { await sharkGit.sync(action); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setSyncing(''); }
  };
  const openBranches = async () => { setBranchMenu(o => !o); try { setBranches((await sharkGit.branches()).branches); } catch { setBranches([]); } };
  const switchTo = (name: string, create = false) => { setBranchMenu(false); setNewBranch(''); void act(() => sharkGit.checkout(name, create)); };

  if (!native) return <p className="search-meta">Source control runs in the desktop app.</p>;
  if (!status) return <p className="search-meta">{error || 'Reading repository…'}</p>;
  if (!status.repo) return <p className="search-meta">This folder is not a git repository. Run <code>git init</code> in the terminal to start tracking it.</p>;
  const staged = status.files.filter(f => f.staged), changes = status.files.filter(f => !f.staged || f.worktree !== ' ');
  const row = (f: GitStatus['files'][number], isStaged: boolean) => <div key={(isStaged ? 's:' : 'c:') + f.path} className="scm-row">
    <button className="scm-file" onClick={() => openPath(f.path)} title={f.path}><FileIcon path={f.path} size={13} /><span className="ellipsis">{f.path.split('/').pop()}</span><small className="ellipsis">{f.path.split('/').slice(0, -1).join('/')}</small></button>
    <button className="icon-btn sm" disabled={busy} aria-label={isStaged ? `Unstage ${f.path}` : `Stage ${f.path}`} title={isStaged ? 'Unstage' : 'Stage'} onClick={() => void act(() => isStaged ? sharkGit.unstage([f.path]) : sharkGit.stage([f.path]))}>{isStaged ? <Minus size={13} /> : <Plus size={13} />}</button>
    <span className={`scm-letter ${f.status}`}>{LETTER[f.status] ?? 'M'}</span>
  </div>;
  return <div className="results scm">
    <div className="scm-branch">
      <div style={{ position: 'relative', minWidth: 0 }}>
        <button className="branch-btn" data-popover-anchor aria-expanded={branchMenu} aria-haspopup="menu" title="Switch branch" onClick={() => void openBranches()}>
          <GitBranch size={13} /><strong className="ellipsis">{status.branch ?? 'detached'}</strong><ChevronDown size={11} />
        </button>
        <Popover open={branchMenu} onClose={() => setBranchMenu(false)} className="branch-pop">
          <form className="branch-new" onSubmit={e => { e.preventDefault(); if (newBranch.trim()) switchTo(newBranch.trim(), true); }}>
            <GitBranchPlus size={12} /><input className="field" placeholder="New branch name" value={newBranch} onChange={e => setNewBranch(e.target.value.replace(/\s+/g, '-'))} autoFocus />
          </form>
          {branches.map(b => <button key={b.name} className="menu-item" role="menuitem" aria-current={b.current} disabled={b.current || busy} onClick={() => switchTo(b.name)}>
            {b.current ? <Check size={12} /> : <span style={{ width: 12 }} />}<span className="ellipsis">{b.name}</span></button>)}
        </Popover>
      </div>
      <span className="grow" />
      <button className="icon-btn sm" aria-label="Fetch" title="Fetch" disabled={!!syncing} onClick={() => void sync('fetch')}><CloudDownload size={12} className={syncing === 'fetch' ? 'spin-slow' : ''} /></button>
      <button className="icon-btn sm sync-btn" aria-label="Pull" title={`Pull (fast-forward only)${status.behind ? ` · ${status.behind} behind` : ''}`} disabled={!!syncing} onClick={() => void sync('pull')}><ArrowDown size={12} />{status.behind ? <small>{status.behind}</small> : null}</button>
      <button className="icon-btn sm sync-btn" aria-label="Push" title={`Push${status.ahead ? ` · ${status.ahead} ahead` : ''}`} disabled={!!syncing} onClick={() => void sync('push')}><ArrowUp size={12} />{status.ahead ? <small>{status.ahead}</small> : null}</button>
      <button className="icon-btn sm" aria-label="Refresh" onClick={() => void refresh()}><RefreshCw size={12} /></button>
    </div>
    <div className="scm-commit">
      <textarea className="field" rows={2} placeholder={staged.length ? `Message (${staged.length} staged)` : 'Stage changes, then write a message'} value={message} onChange={e => setMessage(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && message.trim() && staged.length) void act(async () => { await sharkGit.commit(message.trim()); setMessage(''); }); }} />
      <div className="scm-actions">
        <button className="btn sm primary" disabled={busy || !message.trim() || !staged.length} onClick={() => void act(async () => { await sharkGit.commit(message.trim()); setMessage(''); })}><Check size={12} />Commit</button>
        <button className="btn sm" disabled={!status.files.length} title="Ask Shark to write the message from the diff" onClick={() => askAgent('Write a concise conventional commit message for my staged changes. Read them with git diff --cached. Reply with the message only.')}><Sparkles size={12} />Draft</button>
      </div>
    </div>
    {error && <p className="search-meta" role="alert">{error}</p>}
    {staged.length > 0 && <><div className="run-group">Staged · {staged.length}<span className="grow" /><button className="icon-btn sm" aria-label="Unstage all" onClick={() => void act(() => sharkGit.unstage(staged.map(f => f.path)))}><Minus size={12} /></button></div>{staged.map(f => row(f, true))}</>}
    <div className="run-group">Changes · {changes.length}<span className="grow" />{changes.length > 0 && <button className="icon-btn sm" aria-label="Stage all" onClick={() => void act(() => sharkGit.stage(changes.map(f => f.path)))}><Plus size={12} /></button>}</div>
    {changes.length ? changes.map(f => row(f, false)) : <p className="search-meta">Working tree clean.</p>}
    {log.length > 0 && <><div className="run-group">History</div>{log.map(c => <div key={c.short} className="scm-commit-row" title={`${c.short} · ${c.author}`}><GitCommitHorizontal size={13} /><span className="ellipsis">{c.subject}</span><small>{relativeTime(Number(c.time))}</small></div>)}</>}
  </div>;
}
