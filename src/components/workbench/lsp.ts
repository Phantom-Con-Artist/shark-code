// Language servers for Python, Rust, Go and C/C++, bridged through the Shark runtime.
// TypeScript/JavaScript/JSON/CSS/HTML keep using Monaco's built-in workers.
import { monaco } from './monaco';
import { sharkLsp } from '../../lib/sharkBackend';
import { useProjectStore } from '../../stores/useProjectStore';
import { useUi } from '../../stores/useUi';

type Pos = { line: number; character: number };
type Range = { start: Pos; end: Pos };
type Location = { uri: string; range: Range };
type Markup = string | { kind?: string; value: string; language?: string };
type TextEdit = { range: Range; newText: string };

const LANGS: Record<string, string> = { python: 'python', rust: 'rust', go: 'go', cpp: 'cpp', c: 'c' };
let root = '';
const servers: Record<string, string | null> = {};
const started = new Map<string, Promise<{ triggers: string[]; signature_triggers: string[] } | null>>();
const versions = new Map<string, number>();
let polling: number | undefined;
let installed = false;

const toUri = (model: monaco.editor.ITextModel) => root + model.uri.path.split('/').map(encodeURIComponent).join('/');
const toPath = (uri: string) => uri.startsWith(root + '/') ? decodeURIComponent(uri.slice(root.length + 1)) : null;
const toRange = (r: Range) => new monaco.Range(r.start.line + 1, r.start.character + 1, r.end.line + 1, r.end.character + 1);
const toPos = (p: monaco.Position): Pos => ({ line: p.lineNumber - 1, character: p.column - 1 });
const doc = (model: monaco.editor.ITextModel) => ({ uri: toUri(model) });
const markdown = (m: Markup | Markup[] | undefined): monaco.IMarkdownString[] => {
  const list = Array.isArray(m) ? m : m ? [m] : [];
  return list.map(x => ({ value: typeof x === 'string' ? x : x.language ? '```' + x.language + '\n' + x.value + '\n```' : x.value }));
};
const location = (loc: Location): monaco.languages.Location | null => {
  const path = toPath(loc.uri);
  return path == null ? null : { uri: monaco.Uri.parse(path), range: toRange(loc.range) };
};
const serverFor = (model: monaco.editor.ITextModel) => {
  const lang = LANGS[model.getLanguageId()];
  return lang && servers[lang] && model.uri.scheme === 'file' ? lang : null;
};

function start(lang: string) {
  if (!started.has(lang)) started.set(lang, sharkLsp.start(lang).catch(() => null));
  return started.get(lang)!;
}

async function attach(model: monaco.editor.ITextModel) {
  const lang = serverFor(model);
  if (!lang || !(await start(lang))) return;
  const uri = toUri(model);
  versions.set(uri, 1);
  await sharkLsp.notify(lang, 'textDocument/didOpen', { textDocument: { uri, languageId: lang === 'cpp' ? 'cpp' : lang, version: 1, text: model.getValue() } }).catch(() => undefined);
  let timer: number | undefined;
  const change = model.onDidChangeContent(() => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      const version = (versions.get(uri) ?? 1) + 1;
      versions.set(uri, version);
      void sharkLsp.notify(lang, 'textDocument/didChange', { textDocument: { uri, version }, contentChanges: [{ text: model.getValue() }] }).catch(() => undefined);
    }, 250);
  });
  model.onWillDispose(() => {
    change.dispose(); window.clearTimeout(timer); versions.delete(uri);
    void sharkLsp.notify(lang, 'textDocument/didClose', { textDocument: { uri } }).catch(() => undefined);
  });
  if (polling === undefined) polling = window.setInterval(poll, 1200);
}

async function poll() {
  if (!versions.size) { window.clearInterval(polling); polling = undefined; return; }
  const { diagnostics } = await sharkLsp.poll().catch(() => ({ diagnostics: {} as Awaited<ReturnType<typeof sharkLsp.poll>>['diagnostics'] }));
  for (const [uri, list] of Object.entries(diagnostics)) {
    const path = toPath(uri);
    const model = path == null ? null : monaco.editor.getModel(monaco.Uri.parse(path));
    if (!model) continue;
    monaco.editor.setModelMarkers(model, 'lsp', list.map(d => ({
      ...{ startLineNumber: d.range.start.line + 1, startColumn: d.range.start.character + 1, endLineNumber: d.range.end.line + 1, endColumn: d.range.end.character + 1 },
      message: d.message, source: d.source, code: d.code == null ? undefined : String(d.code),
      severity: d.severity === 1 ? monaco.MarkerSeverity.Error : d.severity === 2 ? monaco.MarkerSeverity.Warning : d.severity === 3 ? monaco.MarkerSeverity.Info : monaco.MarkerSeverity.Hint,
    })));
  }
}

async function ask<T>(model: monaco.editor.ITextModel, method: string, params: object): Promise<T | null> {
  const lang = serverFor(model);
  if (!lang || !(await start(lang))) return null;
  try { return await sharkLsp.request<T>(lang, method, { textDocument: doc(model), ...params }); } catch { return null; }
}

const KIND = monaco.languages.CompletionItemKind;
const KINDS = [KIND.Text, KIND.Text, KIND.Method, KIND.Function, KIND.Constructor, KIND.Field, KIND.Variable, KIND.Class, KIND.Interface, KIND.Module, KIND.Property, KIND.Unit, KIND.Value, KIND.Enum, KIND.Keyword, KIND.Snippet, KIND.Color, KIND.File, KIND.Reference, KIND.Folder, KIND.EnumMember, KIND.Constant, KIND.Struct, KIND.Event, KIND.Operator, KIND.TypeParameter];
const SYMBOL = monaco.languages.SymbolKind;

function register(language: string, triggers: string[], signatureTriggers: string[]) {
  monaco.languages.registerHoverProvider(language, {
    provideHover: async (model, position) => {
      const r = await ask<{ contents: Markup | Markup[]; range?: Range }>(model, 'textDocument/hover', { position: toPos(position) });
      return r ? { contents: markdown(r.contents), range: r.range ? toRange(r.range) : undefined } : null;
    },
  });
  monaco.languages.registerCompletionItemProvider(language, {
    triggerCharacters: triggers,
    provideCompletionItems: async (model, position) => {
      const r = await ask<{ items: CompletionItem[] } | CompletionItem[]>(model, 'textDocument/completion', { position: toPos(position) });
      const items = Array.isArray(r) ? r : r?.items ?? [];
      const word = model.getWordUntilPosition(position);
      const fallback = new monaco.Range(position.lineNumber, word.startColumn, position.lineNumber, word.endColumn);
      return {
        suggestions: items.slice(0, 300).map(i => {
          const edit = i.textEdit && 'range' in i.textEdit ? i.textEdit : null;
          return {
            label: i.label, kind: KINDS[i.kind ?? 1] ?? KIND.Text, detail: i.detail, sortText: i.sortText, filterText: i.filterText,
            documentation: i.documentation ? markdown(i.documentation)[0] : undefined,
            insertText: edit?.newText ?? i.insertText ?? i.label, range: edit ? toRange(edit.range) : fallback,
            insertTextRules: i.insertTextFormat === 2 ? monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet : undefined,
            additionalTextEdits: i.additionalTextEdits?.map(e => ({ range: toRange(e.range), text: e.newText })),
          };
        }),
      };
    },
  });
  monaco.languages.registerDefinitionProvider(language, {
    provideDefinition: async (model, position) => {
      const r = await ask<Location | Location[]>(model, 'textDocument/definition', { position: toPos(position) });
      return (Array.isArray(r) ? r : r ? [r] : []).map(location).filter(Boolean) as monaco.languages.Location[];
    },
  });
  monaco.languages.registerReferenceProvider(language, {
    provideReferences: async (model, position) => {
      const r = await ask<Location[]>(model, 'textDocument/references', { position: toPos(position), context: { includeDeclaration: true } });
      return (r ?? []).map(location).filter(Boolean) as monaco.languages.Location[];
    },
  });
  monaco.languages.registerSignatureHelpProvider(language, {
    signatureHelpTriggerCharacters: signatureTriggers,
    provideSignatureHelp: async (model, position) => {
      const r = await ask<{ signatures: { label: string; documentation?: Markup; parameters?: { label: string | [number, number]; documentation?: Markup }[] }[]; activeSignature?: number; activeParameter?: number }>(model, 'textDocument/signatureHelp', { position: toPos(position) });
      if (!r?.signatures?.length) return null;
      return {
        value: {
          signatures: r.signatures.map(s => ({ label: s.label, documentation: s.documentation ? markdown(s.documentation)[0] : undefined,
            parameters: (s.parameters ?? []).map(p => ({ label: p.label, documentation: p.documentation ? markdown(p.documentation)[0] : undefined })) })),
          activeSignature: r.activeSignature ?? 0, activeParameter: r.activeParameter ?? 0,
        },
        dispose() {},
      };
    },
  });
  monaco.languages.registerDocumentSymbolProvider(language, {
    provideDocumentSymbols: async model => {
      type Sym = { name: string; detail?: string; kind: number; range?: Range; selectionRange?: Range; location?: Location; children?: Sym[] };
      const r = await ask<Sym[]>(model, 'textDocument/documentSymbol', {});
      const map = (s: Sym): monaco.languages.DocumentSymbol => {
        const range = toRange(s.range ?? s.location!.range);
        return { name: s.name, detail: s.detail ?? '', kind: (s.kind ? s.kind - 1 : SYMBOL.Variable) as monaco.languages.SymbolKind, tags: [], range, selectionRange: s.selectionRange ? toRange(s.selectionRange) : range, children: s.children?.map(map) };
      };
      return (r ?? []).filter(s => s.range || s.location).map(map);
    },
  });
  monaco.languages.registerDocumentFormattingEditProvider(language, {
    provideDocumentFormattingEdits: async (model, options) => {
      const r = await ask<TextEdit[]>(model, 'textDocument/formatting', { options: { tabSize: options.tabSize, insertSpaces: options.insertSpaces } });
      return (r ?? []).map(e => ({ range: toRange(e.range), text: e.newText }));
    },
  });
  monaco.languages.registerRenameProvider(language, {
    provideRenameEdits: async (model, position, newName) => {
      const r = await ask<{ changes?: Record<string, TextEdit[]>; documentChanges?: { textDocument: { uri: string }; edits: TextEdit[] }[] }>(model, 'textDocument/rename', { position: toPos(position), newName });
      const groups = r?.documentChanges?.map(d => [d.textDocument.uri, d.edits] as const) ?? Object.entries(r?.changes ?? {});
      const edits: monaco.languages.IWorkspaceTextEdit[] = [];
      for (const [uri, list] of groups) {
        const path = toPath(uri);
        if (path == null) continue;
        for (const e of list) edits.push({ resource: monaco.Uri.parse(path), versionId: undefined, textEdit: { range: toRange(e.range), text: e.newText } });
      }
      return { edits };
    },
  });
}

type CompletionItem = {
  label: string; kind?: number; detail?: string; documentation?: Markup; sortText?: string; filterText?: string; insertText?: string; insertTextFormat?: number;
  textEdit?: { range: Range; newText: string } | { insert: Range; replace: Range; newText: string }; additionalTextEdits?: TextEdit[];
};

/** Connect the editor to the project's language servers. Safe to call more than once. */
export async function installLanguageServers() {
  if (installed) return;
  installed = true;
  try {
    const info = await sharkLsp.servers();
    root = info.root.replace(/\/$/, '');
    Object.assign(servers, info.servers);
  } catch { installed = false; return; }
  for (const [language, server] of Object.entries(servers)) {
    if (!server) continue;
    // Providers are registered up front and start the server lazily on first use.
    const triggers = language === 'python' ? ['.', '[', '"', "'"] : language === 'rust' ? ['.', ':', '<'] : ['.', ':', '>', '"', '/', '<'];
    register(language, triggers, ['(', ',']);
  }
  monaco.editor.onDidCreateModel(model => { void attach(model); });
  for (const model of monaco.editor.getModels()) void attach(model);
  // Go to definition / references across files opens the target in a Shark tab.
  monaco.editor.registerEditorOpener({
    openCodeEditor(_source, resource, selection) {
      if (resource.scheme !== 'file') return false;
      const path = resource.path.replace(/^\//, '');
      void useProjectStore.getState().openFile(path);
      const line = selection && 'startLineNumber' in selection ? selection.startLineNumber : (selection as monaco.IPosition | undefined)?.lineNumber;
      useUi.getState().set({ editorView: 'file', ...(line ? { reveal: { path, line } } : {}) });
      return true;
    },
  });
}

/** Which languages have a working server on this machine (for the status bar). */
export function languageServerFor(language: string) {
  const lang = LANGS[language];
  return lang ? servers[lang] ?? null : null;
}
