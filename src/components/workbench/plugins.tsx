import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, BarChart3, Bell, Book, Bookmark, Bot, Boxes, Brain, Bug, Calendar, CheckSquare, ClipboardList, Clock, Cloud, Code2, Compass, Cpu, Database, FileText, Flag, Gauge, GitBranch, Globe, Hammer, Heart, Image, Inbox, Key, Layers, Layout, Lightbulb, ListTodo, Lock, Map, MessageCircle, Monitor, Network, Notebook, Package, Palette, PenTool, Puzzle, Rocket, Search, Server, Settings, Shield, Sparkles, Star, Table, Tag, Target, Terminal, TestTube2, Timer, Wand2, Workflow, Wrench, Zap } from 'lucide-react';

const Icons = { Activity, BarChart3, Bell, Book, Bookmark, Bot, Boxes, Brain, Bug, Calendar, CheckSquare, ClipboardList, Clock, Cloud, Code2, Compass, Cpu, Database, FileText, Flag, Gauge, GitBranch, Globe, Hammer, Heart, Image, Inbox, Key, Layers, Layout, Lightbulb, ListTodo, Lock, Map, MessageCircle, Monitor, Network, Notebook, Package, Palette, PenTool, Puzzle, Rocket, Search, Server, Settings, Shield, Sparkles, Star, Table, Tag, Target, Terminal, TestTube2, Timer, Wand2, Workflow, Wrench, Zap };
export const PLUGIN_ICONS = Object.keys(Icons);
import { useProjectStore } from '../../stores/useProjectStore';
import { useSettings } from '../../stores/useSettings';
import { useUi } from '../../stores/useUi';
import { askAgent } from './BottomPanel';

/**
 * Shark plugins live in the project at .sharkcode/plugins/<id>/ with:
 *   plugin.json  { "name", "description", "icon" (lucide name), "permissions": ["files.read","files.open","agent.ask","terminal.run"] }
 *   panel.html   the sidebar view, rendered in a sandboxed iframe (scripts only, no same-origin access).
 * The panel talks to Shark with postMessage: { type: "shark:request", id, method, params } → { type: "shark:response", id, result | error }.
 */
export const PLUGIN_ROOT = '.sharkcode/plugins';
export const PERMISSIONS = { 'files.read': 'Read project files', 'files.open': 'Open files in the editor', 'agent.ask': 'Draft messages to the agent', 'terminal.run': 'Run commands in the terminal' } as const;
type Permission = keyof typeof PERMISSIONS;
export type Plugin = { id: string; name: string; description: string; icon: string; permissions: Permission[]; error?: string };

export function PluginIcon({ name, size = 20 }: { name: string; size?: number }) {
  const Icon = (Icons as Record<string, typeof Puzzle>)[name] ?? Puzzle;
  return <Icon size={size} strokeWidth={1.6} />;
}

let cache: { key: string; plugins: Plugin[] } | null = null;
export function usePlugins() {
  const entries = useProjectStore(s => s.entries);
  const readText = useProjectStore(s => s.readText);
  const disabled = useSettings(s => s.disabledPlugins);
  const manifests = useMemo(() => entries.filter(e => !e.directory && e.path.startsWith(PLUGIN_ROOT + '/') && e.path.endsWith('/plugin.json') && e.path.split('/').length === 4).map(e => e.path), [entries]);
  const key = manifests.join('|');
  const [plugins, setPlugins] = useState<Plugin[]>(() => cache?.key === key ? cache.plugins : []);
  useEffect(() => {
    let live = true;
    void Promise.all(manifests.map(async path => {
      const id = path.split('/')[2];
      try {
        const m = JSON.parse((await readText(path)) ?? '{}');
        const permissions = (Array.isArray(m.permissions) ? m.permissions : []).filter((p: string) => p in PERMISSIONS);
        return { id, name: String(m.name || id).slice(0, 40), description: String(m.description || '').slice(0, 200), icon: String(m.icon || 'Puzzle'), permissions };
      } catch { return { id, name: id, description: '', icon: 'Puzzle', permissions: [], error: 'plugin.json is not valid JSON' }; }
    })).then(list => { if (live) { cache = { key, plugins: list }; setPlugins(list); } });
    return () => { live = false; };
  }, [key, manifests, readText]);
  return { all: plugins, enabled: plugins.filter(p => !p.error && !disabled.includes(p.id)) };
}

/** Sandboxed plugin view with a permission-checked bridge. */
export function PluginView({ plugin }: { plugin: Plugin }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const readText = useProjectStore(s => s.readText);
  const theme = useUi(u => u.resolvedTheme);
  const [html, setHtml] = useState<string | null>(null);
  useEffect(() => { void readText(`${PLUGIN_ROOT}/${plugin.id}/panel.html`).then(t => setHtml(t ?? '')); }, [plugin.id, readText]);

  useEffect(() => {
    const onMessage = async (e: MessageEvent) => {
      if (e.source !== frame.current?.contentWindow || e.data?.type !== 'shark:request') return;
      const { id, method, params = {} } = e.data as { id: string; method: string; params: Record<string, string> };
      const reply = (body: object) => frame.current?.contentWindow?.postMessage({ type: 'shark:response', id, ...body }, '*');
      const need = (p: Permission) => { if (!plugin.permissions.includes(p)) throw new Error(`Permission "${p}" is not declared in plugin.json`); };
      try {
        const project = useProjectStore.getState();
        if (method === 'files.list') { need('files.read'); reply({ result: project.entries.filter(x => !x.directory).map(x => x.path).slice(0, 5000) }); }
        else if (method === 'files.read') { need('files.read'); reply({ result: await project.readText(String(params.path)) }); }
        else if (method === 'files.open') { need('files.open'); await project.openFile(String(params.path)); useUi.getState().set({ editorView: 'file' }); reply({ result: true }); }
        else if (method === 'agent.ask') { need('agent.ask'); askAgent(String(params.text).slice(0, 8000)); reply({ result: true }); }
        else if (method === 'terminal.run') {
          need('terminal.run');
          if (!window.confirm(`${plugin.name} wants to run:\n\n${params.command}\n\nAllow?`)) throw new Error('The person declined');
          const { runTask } = await import('./Sidebar'); await runTask({ command: String(params.command) }); reply({ result: true });
        }
        else if (method === 'context.get') reply({ result: { activePath: project.activePath, theme: useUi.getState().resolvedTheme, project: project.name } });
        else throw new Error(`Unknown method ${method}`);
      } catch (err) { reply({ error: err instanceof Error ? err.message : String(err) }); }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [plugin]);

  if (html === null) return <p className="search-meta">Loading plugin…</p>;
  if (!html) return <p className="search-meta">{plugin.id}/panel.html is missing.</p>;
  const bridge = `<script>window.shark={request(method,params){return new Promise((res,rej)=>{const id=Math.random().toString(36).slice(2);const on=e=>{if(e.data&&e.data.type==='shark:response'&&e.data.id===id){removeEventListener('message',on);e.data.error?rej(new Error(e.data.error)):res(e.data.result)}};addEventListener('message',on);parent.postMessage({type:'shark:request',id,method,params},'*')})}};document.documentElement.dataset.theme=${JSON.stringify(theme)};</script>`;
  const base = `<style>:root{color-scheme:${theme}}body{margin:0;padding:10px 12px;font:13px/1.5 system-ui,sans-serif;color:${theme === 'dark' ? '#e6e8ec' : '#262a31'};background:transparent}button{font:inherit}</style>`;
  return <iframe ref={frame} key={theme} className="plugin-frame" title={plugin.name} sandbox="allow-scripts allow-forms" srcDoc={bridge + base + html} />;
}

export function pluginPrompt(idea: string) {
  const text = idea.trim();
  const id = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 32) || 'my-plugin';
  return `Create a Shark plugin: ${text}

Write exactly these files:
- ${PLUGIN_ROOT}/${id}/plugin.json: {"name": short title, "description": one sentence, "icon": one of ${PLUGIN_ICONS.join(", ")}, "permissions": only what it needs from ["files.read","files.open","agent.ask","terminal.run"]}
- ${PLUGIN_ROOT}/${id}/panel.html: a self-contained sidebar view (inline CSS and JS, no external network requests, no frameworks).

The panel runs in a sandboxed iframe about 280px wide. Call Shark with \`await shark.request(method, params)\`:
files.list() → string[] · files.read({path}) → string · files.open({path}) · agent.ask({text}) · terminal.run({command}) · context.get() → {activePath, theme, project}.
document.documentElement.dataset.theme is "light" or "dark"; style for both with subtle neutral colours and compact 13px text.`;
}

export function PluginManager() {
  const { all } = usePlugins();
  const s = useSettings();
  const [idea, setIdea] = useState('');
  const create = () => { if (idea.trim()) { askAgent(pluginPrompt(idea)); setIdea(''); } };
  return <div className="results plugin-manager">
    <section className="plugin-create">
      <label className="label" htmlFor="plugin-idea">Create with AI</label>
      <textarea id="plugin-idea" className="field" rows={3} value={idea} placeholder="e.g. A TODO board that collects TODO comments and opens them on click" onChange={e => setIdea(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) create(); }} />
      <button className="btn accent sm" disabled={!idea.trim()} onClick={create}><Sparkles size={12} />Draft with agent</button>
      <p className="fine">The agent writes the plugin as a normal proposal. Review and apply it, and it appears in the side strip.</p>
    </section>
    <div className="run-group">Installed · {all.length}</div>
    {!all.length && <p className="search-meta">No plugins in {PLUGIN_ROOT} yet.</p>}
    {all.map(p => { const on = !p.error && !s.disabledPlugins.includes(p.id); return <div key={p.id} className="plugin-row">
      <span className="plugin-icon"><PluginIcon name={p.icon} size={16} /></span>
      <span className="text"><strong>{p.name}</strong><small>{p.error ?? (p.description || p.id)}</small>
        {p.permissions.length > 0 && <small className="perms">{p.permissions.map(x => PERMISSIONS[x]).join(' · ')}</small>}</span>
      <input type="checkbox" className="switch" aria-label={`Enable ${p.name}`} checked={on} disabled={!!p.error}
        onChange={e => s.set({ disabledPlugins: e.target.checked ? s.disabledPlugins.filter(x => x !== p.id) : [...s.disabledPlugins, p.id] })} />
    </div>; })}
  </div>;
}
