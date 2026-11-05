import React, { useRef } from 'react';
import Editor, { DiffEditor, OnMount } from '@monaco-editor/react';
import type * as monaco from 'monaco-editor';
import { X, Check, Undo2, FileCode } from 'lucide-react';
import { useEditorStore } from '@/stores/useEditorStore';

export const EditorArea: React.FC = () => {
  const {
    tabs,
    activeTabId,
    activeDiff,
    setActiveTab,
    closeTab,
    updateContent,
    setCursorPosition,
    acceptDiff,
    rejectDiff,
  } = useEditorStore();

  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);

  const activeTab = tabs.find((t) => t.id === activeTabId);

  const handleEditorMount: OnMount = (editor) => {
    editorRef.current = editor;
    editor.onDidChangeCursorPosition((e) => {
      setCursorPosition({ line: e.position.lineNumber, column: e.position.column });
    });
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#1e1e1e] overflow-hidden">
      {/* Tab Bar */}
      <div className="flex items-center bg-[#18181b] border-b border-[#27272a] overflow-x-auto select-none h-9 shrink-0">
        {tabs.map((tab) => {
          const isActive = tab.id === activeTabId && !activeDiff;
          return (
            <div
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id);
                if (activeDiff) rejectDiff();
              }}
              className={`flex items-center space-x-2 px-3 py-1.5 text-xs border-r border-[#27272a] cursor-pointer h-full transition-colors group ${
                isActive
                  ? 'bg-[#1e1e1e] text-white border-t-2 border-t-blue-500 font-medium'
                  : 'bg-[#18181b] text-zinc-400 hover:text-zinc-200 hover:bg-[#1f1f23]'
              }`}
            >
              <FileCode size={13} className={isActive ? 'text-blue-400' : 'text-zinc-500'} />
              <span className="truncate max-w-[140px]">{tab.name}</span>
              {tab.isDirty && <div className="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(tab.id);
                }}
                className="opacity-0 group-hover:opacity-100 hover:bg-zinc-700/60 p-0.5 rounded text-zinc-400 hover:text-white transition-opacity"
              >
                <X size={12} />
              </button>
            </div>
          );
        })}

        {activeDiff && (
          <div className="flex items-center space-x-2 px-3 py-1.5 text-xs bg-amber-950/40 border-r border-amber-900 text-amber-200 h-full border-t-2 border-t-amber-500 font-medium animate-pulse">
            <span>Agent Proposed Diff: {activeDiff.filePath.split('/').pop()}</span>
          </div>
        )}
      </div>

      {/* Diff Banner if in Diff Mode */}
      {activeDiff && (
        <div className="bg-amber-950/60 border-b border-amber-900/80 px-4 py-2 flex items-center justify-between text-xs text-amber-100 shrink-0">
          <div className="flex items-center space-x-2">
            <span className="font-semibold text-amber-400">Reviewing Agent Changes:</span>
            <span className="font-mono text-zinc-300">{activeDiff.filePath}</span>
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={() => acceptDiff(activeDiff.filePath)}
              className="flex items-center space-x-1.5 bg-emerald-600 hover:bg-emerald-500 text-white px-2.5 py-1 rounded transition-colors font-medium shadow-sm"
            >
              <Check size={13} />
              <span>Accept & Apply</span>
            </button>
            <button
              onClick={rejectDiff}
              className="flex items-center space-x-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-2.5 py-1 rounded transition-colors"
            >
              <Undo2 size={13} />
              <span>Reject</span>
            </button>
          </div>
        </div>
      )}

      {/* Editor Content Area */}
      <div className="flex-1 relative overflow-hidden">
        {activeDiff ? (
          <DiffEditor
            height="100%"
            language={activeTab?.language || 'typescript'}
            original={activeDiff.originalContent}
            modified={activeDiff.newContent}
            theme="vs-dark"
            options={{
              renderSideBySide: true,
              readOnly: true,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              fontSize: 13,
            }}
          />
        ) : activeTab ? (
          <Editor
            height="100%"
            language={activeTab.language}
            value={activeTab.content}
            theme="vs-dark"
            onChange={(val) => updateContent(activeTab.id, val || '')}
            onMount={handleEditorMount}
            options={{
              minimap: { enabled: true },
              fontSize: 13,
              fontFamily: "'Fira Code', 'Cascadia Code', Menlo, Monaco, 'Courier New', monospace",
              fontLigatures: true,
              scrollBeyondLastLine: false,
              lineNumbers: 'on',
              roundedSelection: false,
              automaticLayout: true,
              tabSize: 2,
              wordWrap: 'on',
            }}
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-zinc-500 select-none space-y-2">
            <FileCode size={40} strokeWidth={1.2} />
            <p className="text-sm">No file open</p>
            <p className="text-xs text-zinc-600">Select a file from the explorer or ask the agent to create one.</p>
          </div>
        )}
      </div>
    </div>
  );
};
