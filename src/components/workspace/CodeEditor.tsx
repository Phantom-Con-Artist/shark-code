import Editor, { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor/editor/editor.api.js';
import 'monaco-editor/features/find/register.js';
import 'monaco-editor/features/bracketMatching/register.js';
import 'monaco-editor/features/comment/register.js';
import 'monaco-editor/features/wordOperations/register.js';
import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker';
import 'monaco-editor/languages/definitions/typescript/register.js';
import 'monaco-editor/languages/definitions/javascript/register.js';
import 'monaco-editor/languages/definitions/css/register.js';
import 'monaco-editor/languages/definitions/html/register.js';
import 'monaco-editor/languages/definitions/rust/register.js';
import 'monaco-editor/languages/definitions/markdown/register.js';
import { useProjectStore } from '../../stores/useProjectStore';

self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });
monaco.editor.defineTheme('shark', { base: 'vs-dark', inherit: true, rules: [], colors: { 'editor.background': '#18181a', 'editor.foreground': '#dedee5', 'editorLineNumber.foreground': '#85858e', 'editor.lineHighlightBackground': '#222225', 'editor.selectionBackground': '#3e5a50', 'editorCursor.foreground': '#9bcbb6' } });
function language(path: string) { const ext = path.split('.').pop(); return ({ tsx: 'typescript', ts: 'typescript', js: 'javascript', jsx: 'javascript', css: 'css', html: 'html', json: 'json', rs: 'rust', md: 'markdown' } as Record<string, string>)[ext || ''] || 'plaintext'; }
export default function CodeEditor() {
  const { tabs, activePath, edit, save } = useProjectStore();
  const file = tabs.find(t => t.path === activePath);
  if (!file) return <div className="editor-empty">Choose a file in the explorer to start editing.</div>;
  return <Editor path={file.path} language={language(file.path)} theme="shark" value={file.content} onChange={value => edit(file.path, value ?? '')} loading={<div className="editor-empty">Opening editor…</div>} onMount={editor => {
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => { const state = useProjectStore.getState(); void save(state.activePath); });
  }} options={{ editContext: false, automaticLayout: true, minimap: { enabled: false }, fontSize: 12, lineHeight: 22, padding: { top: 14 }, scrollBeyondLastLine: false, wordWrap: 'on', tabSize: 2, renderLineHighlight: 'line', overviewRulerLanes: 0, stickyScroll: { enabled: false }, fixedOverflowWidgets: true, ariaLabel: `Edit ${file.path}` }}/>;
}
