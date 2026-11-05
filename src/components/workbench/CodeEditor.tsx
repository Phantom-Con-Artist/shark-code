import { useEffect, useRef } from 'react';
import Editor, { DiffEditor } from '@monaco-editor/react';
import { monaco } from './monaco';
import { languageOf } from './primitives';
import { installLanguageServers } from './lsp';
import { useProjectStore } from '../../stores/useProjectStore';
import { useSettings } from '../../stores/useSettings';
import { useUi } from '../../stores/useUi';

let activeEditor: monaco.editor.IStandaloneCodeEditor | null = null;
/** Run a Monaco action on the current editor (used by the menu bar). Returns false when no editor is open. */
export function runEditorAction(id: string) {
  if (!activeEditor) return false;
  activeEditor.focus();
  activeEditor.trigger('menu', id, null);
  return true;
}

function useBaseOptions(): monaco.editor.IStandaloneEditorConstructionOptions {
  const s = useSettings();
  return {
    fontFamily: "'Geist Mono Variable', ui-monospace, monospace", fontSize: s.editorFontSize, fontLigatures: true,
    lineHeight: Math.round(s.editorFontSize * (s.density === 'comfortable' ? 1.85 : 1.65)),
    minimap: { enabled: s.minimap, renderCharacters: false, scale: 1 }, wordWrap: s.wordWrap ? 'on' : 'off',
    accessibilitySupport: 'auto', cursorBlinking: s.reduceMotion ? 'solid' : 'smooth', cursorSmoothCaretAnimation: s.reduceMotion ? 'off' : 'on',
    smoothScrolling: !s.reduceMotion, padding: { top: 12, bottom: 12 }, scrollBeyondLastLine: false, automaticLayout: true,
    renderLineHighlight: 'line', overviewRulerLanes: 0, hideCursorInOverviewRuler: true, overviewRulerBorder: false,
    scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10, useShadows: false },
    guides: { indentation: true, bracketPairs: false }, bracketPairColorization: { enabled: false },
    fixedOverflowWidgets: true, editContext: false, tabSize: 2, lineNumbersMinChars: 4, folding: true, showFoldingControls: 'mouseover',
  };
}

export function useMonacoTheme() {
  return useUi(s => s.resolvedTheme) === 'light' ? 'shark-light' : 'shark-dark';
}

export default function CodeEditor() {
  const { tabs, activePath, edit, save } = useProjectStore();
  const options = useBaseOptions();
  const theme = useMonacoTheme();
  const reveal = useUi(s => s.reveal);
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const file = tabs.find(t => t.path === activePath);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !reveal || reveal.path !== activePath) return;
    editor.revealLineInCenter(reveal.line);
    editor.setPosition({ lineNumber: reveal.line, column: 1 });
    editor.focus();
    useUi.getState().set({ reveal: null });
  }, [reveal, activePath, file?.path]);

  if (!file) return null;
  return <Editor
    path={file.path} language={languageOf(file.path)[0]} theme={theme} value={file.content}
    onChange={value => edit(file.path, value ?? '')}
    loading={<div className="editor-empty">Opening…</div>}
    onMount={editor => {
      editorRef.current = editor; activeEditor = editor;
      if (useProjectStore.getState().kind === 'native') void installLanguageServers();
      editor.onDidDispose(() => { if (activeEditor === editor) activeEditor = null; });
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => { void save(useProjectStore.getState().activePath); });
      const r = useUi.getState().reveal;
      if (r && r.path === file.path) { editor.revealLineInCenter(r.line); editor.setPosition({ lineNumber: r.line, column: 1 }); useUi.getState().set({ reveal: null }); }
    }}
    options={{ ...options, ariaLabel: `Editing ${file.path}` }}
  />;
}

export function DiffView({ path, original, modified, inline }: { path: string; original: string; modified: string; inline: boolean }) {
  const options = useBaseOptions();
  const theme = useMonacoTheme();
  return <DiffEditor
    original={original} modified={modified} language={languageOf(path)[0]} theme={theme}
    originalModelPath={`shark-review-before://${path}`} modifiedModelPath={`shark-review-after://${path}`}
    loading={<div className="editor-empty">Loading changes…</div>}
    options={{ ...options, readOnly: true, originalEditable: false, renderSideBySide: !inline, useInlineViewWhenSpaceIsLimited: true,
      renderOverviewRuler: false, hideUnchangedRegions: { enabled: true, contextLineCount: 3, minimumLineCount: 4 }, renderIndicators: true, ignoreTrimWhitespace: false }}
  />;
}
