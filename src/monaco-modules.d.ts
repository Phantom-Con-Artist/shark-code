// Monaco 0.57 ships these ESM entry points without type declarations.
declare module 'monaco-editor/language/typescript/monaco.contribution.js' {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  type Defaults = { setCompilerOptions(o: object): void; setDiagnosticsOptions(o: object): void; setEagerModelSync(v: boolean): void; setInlayHintsOptions?(o: object): void; addExtraLib(content: string, path?: string): { dispose(): void } };
  export const typescriptDefaults: Defaults;
  export const javascriptDefaults: Defaults;
  export const ScriptTarget: Record<string, number>;
  export const ModuleKind: Record<string, number>;
  export const ModuleResolutionKind: Record<string, number>;
  export const JsxEmit: Record<string, number>;
}
