import { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor/editor/editor.api.js';
import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker';
import TsWorker from 'monaco-editor/language/typescript/ts.worker.js?worker';
import JsonWorker from 'monaco-editor/language/json/json.worker.js?worker';
import CssWorker from 'monaco-editor/language/css/css.worker.js?worker';
import HtmlWorker from 'monaco-editor/language/html/html.worker.js?worker';
import * as ts from 'monaco-editor/language/typescript/monaco.contribution.js';
import 'monaco-editor/language/json/monaco.contribution.js';
import 'monaco-editor/language/css/monaco.contribution.js';
import 'monaco-editor/language/html/monaco.contribution.js';
import 'monaco-editor/features/hover/register.js';
import 'monaco-editor/features/parameterHints/register.js';
import 'monaco-editor/features/gotoSymbol/register.js';
import 'monaco-editor/features/gotoError/register.js';
import 'monaco-editor/features/rename/register.js';
import 'monaco-editor/features/codeAction/register.js';
import 'monaco-editor/features/format/register.js';
import 'monaco-editor/features/quickOutline/register.js';
import 'monaco-editor/features/quickCommand/register.js';
import 'monaco-editor/features/inlayHints/register.js';
import 'monaco-editor/features/documentSymbols/register.js';
import 'monaco-editor/features/snippet/register.js';
import 'monaco-editor/features/links/register.js';
import 'monaco-editor/features/colorPicker/register.js';
import 'monaco-editor/features/semanticTokens/register.js';
import 'monaco-editor/features/find/register.js';
import 'monaco-editor/features/bracketMatching/register.js';
import 'monaco-editor/features/comment/register.js';
import 'monaco-editor/features/wordOperations/register.js';
import 'monaco-editor/features/folding/register.js';
import 'monaco-editor/features/multicursor/register.js';
import 'monaco-editor/features/linesOperations/register.js';
import 'monaco-editor/features/clipboard/register.js';
import 'monaco-editor/features/contextmenu/register.js';
import 'monaco-editor/features/gotoLine/register.js';
import 'monaco-editor/features/indentation/register.js';
import 'monaco-editor/features/cursorUndo/register.js';
import 'monaco-editor/features/wordHighlighter/register.js';
import 'monaco-editor/features/smartSelect/register.js';
import 'monaco-editor/features/suggest/register.js';
import 'monaco-editor/features/diffEditor/register.js';
import 'monaco-editor/features/toggleTabFocusMode/register.js';
import 'monaco-editor/languages/definitions/typescript/register.js';
import 'monaco-editor/languages/definitions/javascript/register.js';
import 'monaco-editor/languages/definitions/css/register.js';
import 'monaco-editor/languages/definitions/scss/register.js';
import 'monaco-editor/languages/definitions/less/register.js';
import 'monaco-editor/languages/definitions/html/register.js';
import 'monaco-editor/languages/definitions/xml/register.js';
import 'monaco-editor/languages/definitions/rust/register.js';
import 'monaco-editor/languages/definitions/markdown/register.js';
import 'monaco-editor/languages/definitions/python/register.js';
import 'monaco-editor/languages/definitions/go/register.js';
import 'monaco-editor/languages/definitions/java/register.js';
import 'monaco-editor/languages/definitions/kotlin/register.js';
import 'monaco-editor/languages/definitions/swift/register.js';
import 'monaco-editor/languages/definitions/cpp/register.js';
import 'monaco-editor/languages/definitions/sql/register.js';
import 'monaco-editor/languages/definitions/yaml/register.js';
import 'monaco-editor/languages/definitions/ini/register.js';
import 'monaco-editor/languages/definitions/shell/register.js';
import 'monaco-editor/languages/definitions/dockerfile/register.js';

self.MonacoEnvironment = {
  getWorker(_id: string, label: string) {
    if (label === 'typescript' || label === 'javascript') return new TsWorker();
    if (label === 'json') return new JsonWorker();
    if (label === 'css' || label === 'scss' || label === 'less') return new CssWorker();
    if (label === 'html' || label === 'handlebars' || label === 'razor') return new HtmlWorker();
    return new EditorWorker();
  },
};

// Language service: real completions, hovers, go-to-definition and diagnostics for open files.
// Packages outside the open files are not loaded, so "cannot find module" style errors are muted.
const compilerOptions = {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.NodeJs,
  jsx: ts.JsxEmit.ReactJSX, allowJs: true, allowNonTsExtensions: true, esModuleInterop: true, strict: true, skipLibCheck: true, isolatedModules: true,
};
const diagnostics = { noSemanticValidation: false, noSyntaxValidation: false, diagnosticCodesToIgnore: [2307, 2792, 7016, 2875, 1259, 2686] };
for (const defaults of [ts.typescriptDefaults, ts.javascriptDefaults]) {
  defaults.setCompilerOptions(compilerOptions);
  defaults.setDiagnosticsOptions(diagnostics);
  defaults.setEagerModelSync(true);
  defaults.setInlayHintsOptions?.({ includeInlayParameterNameHints: 'none' });
}
loader.config({ monaco });

// Hex values mirror the --editor surface tokens in App.css.
monaco.editor.defineTheme('shark-dark', {
  base: 'vs-dark', inherit: true,
  rules: [
    { token: 'comment', foreground: '6b7280', fontStyle: 'italic' },
    { token: 'keyword', foreground: 'c4a7f5' },
    { token: 'string', foreground: 'a8d4a0' },
    { token: 'number', foreground: 'f0b88a' },
    { token: 'type', foreground: '7cc4f0' },
    { token: 'type.identifier', foreground: '7cc4f0' },
    { token: 'delimiter', foreground: '9aa1ad' },
  ],
  colors: {
    'editor.background': '#1a1a1a', 'editor.foreground': '#e8f5ef',
    'editorLineNumber.foreground': '#4e564f', 'editorLineNumber.activeForeground': '#a9b3af',
    'editor.lineHighlightBackground': '#202221', 'editor.lineHighlightBorder': '#00000000',
    'editor.selectionBackground': '#1f5c40', 'editor.inactiveSelectionBackground': '#20332a',
    'editorCursor.foreground': '#00e68a', 'editorIndentGuide.background1': '#262826', 'editorIndentGuide.activeBackground1': '#3a3d3a',
    'editorWidget.background': '#1f1f1f', 'editorWidget.border': '#2e302e', 'editorSuggestWidget.background': '#1f1f1f',
    'scrollbarSlider.background': '#ffffff14', 'scrollbarSlider.hoverBackground': '#ffffff24',
    'diffEditor.insertedTextBackground': '#00e68a1f', 'diffEditor.removedTextBackground': '#e5534b1f',
    'diffEditor.insertedLineBackground': '#00e68a12', 'diffEditor.removedLineBackground': '#e5534b12',
    'editorGutter.background': '#1a1a1a', 'focusBorder': '#00000000',
  },
});
monaco.editor.defineTheme('shark-light', {
  base: 'vs', inherit: true,
  rules: [
    { token: 'comment', foreground: '8a919c', fontStyle: 'italic' },
    { token: 'keyword', foreground: '7c3aed' },
    { token: 'string', foreground: '2f7d32' },
    { token: 'number', foreground: 'b45309' },
    { token: 'type', foreground: '0369a1' },
    { token: 'type.identifier', foreground: '0369a1' },
  ],
  colors: {
    'editor.background': '#fcfcfd', 'editor.foreground': '#262a31',
    'editorLineNumber.foreground': '#b4b9c2', 'editorLineNumber.activeForeground': '#4b515c',
    'editor.lineHighlightBackground': '#f3f4f7', 'editor.lineHighlightBorder': '#00000000',
    'editor.selectionBackground': '#cdeedd', 'editorCursor.foreground': '#00875f',
    'editorIndentGuide.background1': '#eceef1', 'editorIndentGuide.activeBackground1': '#d5d9df',
    'editorWidget.background': '#ffffff', 'editorWidget.border': '#e2e5ea',
    'diffEditor.insertedTextBackground': '#16a34a1f', 'diffEditor.removedTextBackground': '#dc26261a',
    'diffEditor.insertedLineBackground': '#16a34a0f', 'diffEditor.removedLineBackground': '#dc26260d',
    'editorGutter.background': '#fcfcfd', 'focusBorder': '#00000000',
  },
});

export { monaco };

// Re-measure once web fonts arrive so the cursor and glyph widths line up.
void document.fonts?.ready.then(() => monaco.editor.remeasureFonts());

// Publish diagnostics for the Problems panel and status bar.
import { useUi, type Problem } from '../../stores/useUi';
monaco.editor.onDidChangeMarkers(() => {
  const problems: Problem[] = monaco.editor.getModelMarkers({})
    .filter(m => m.severity >= monaco.MarkerSeverity.Warning && !m.resource.scheme.startsWith('shark-review'))
    .map(m => ({ path: m.resource.path.replace(/^\//, ''), line: m.startLineNumber, column: m.startColumn, message: m.message, severity: m.severity === monaco.MarkerSeverity.Error ? 'error' : 'warning', source: m.source || m.owner }));
  useUi.getState().set({ problems });
});
