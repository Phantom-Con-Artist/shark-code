import React, { useState, useRef, useEffect } from 'react';
import {
  Send,
  Sparkles,
  Bot,
  User,
  Wrench,
  ChevronDown,
  GitCompare,
  Trash2,
  Terminal,
  Search,
  Eye,
} from 'lucide-react';
import { useAgentStore, AVAILABLE_MODELS } from '@/stores/useAgentStore';
import { useEditorStore } from '@/stores/useEditorStore';

export const AgentSidebar: React.FC = () => {
  const {
    messages,
    selectedModel,
    isStreaming,
    setSelectedModel,
    addMessage,
    updateMessageContent,
    setIsStreaming,
    clearHistory,
  } = useAgentStore();

  const { setActiveDiff } = useEditorStore();

  const [input, setInput] = useState('');
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, isStreaming]);

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim() || isStreaming) return;

    const userText = input;
    setInput('');

    addMessage({
      sender: 'user',
      content: userText,
    });

    setIsStreaming(true);

    const agentMsgId = addMessage({
      sender: 'agent',
      content: '',
      thinking: 'Analyzing workspace structure and checking active buffers...',
      toolCalls: [
        {
          id: 'tc-1',
          name: 'tree_sitter.get_symbol_outline',
          args: { path: 'src/stores/useEditorStore.ts' },
          status: 'running',
        },
      ],
    });

    // Simulate agentic tool loop and diff proposal
    setTimeout(() => {
      updateMessageContent(
        agentMsgId,
        `I explored the codebase using Tree-sitter and found the state management store. Here is a proposed optimization to add atomic checkpoint snapshots to the editor.`,
        'Tree-sitter outline retrieved in 4ms. Ripgrep pattern matching confirmed 0 conflicts.'
      );

      // Attach proposed diff to the message
      const proposedDiff = {
        filePath: '/home/subhradeep/Development/shark code/src/stores/useEditorStore.ts',
        originalContent: `// Original content\nexport const useEditorStore = create<EditorState>((set) => ({ ... }));`,
        newContent: `// Optimized with Shark Code Checkpoints\nexport const useEditorStore = create<EditorState>((set, get) => ({\n  // Added atomic checkpoint reflog\n  checkpointId: 'turn-9482',\n  createCheckpoint: () => console.log('Checkpoint saved'),\n  ...state\n}));`,
        status: 'pending' as const,
      };

      useAgentStore.setState((s) => ({
        messages: s.messages.map((m) =>
          m.id === agentMsgId
            ? {
                ...m,
                toolCalls: [
                  {
                    id: 'tc-1',
                    name: 'tree_sitter.get_symbol_outline',
                    args: { path: 'src/stores/useEditorStore.ts' },
                    status: 'success',
                    result: 'Found 12 symbols, 4 functions, 2 interfaces in 4ms',
                  },
                ],
                proposedDiffs: [proposedDiff],
              }
            : m
        ),
      }));

      setIsStreaming(false);
    }, 1200);
  };

  const handleInspectWorkspace = () => {
    setInput('Explore the project structure and give me an AST summary of key components.');
  };

  const handleTriggerDiff = () => {
    const diff = {
      filePath: '/home/subhradeep/Development/shark code/src/stores/useEditorStore.ts',
      originalContent: `export const useEditorStore = create<EditorState>((set, get) => ({\n  tabs: [],\n  activeTabId: null,\n}));`,
      newContent: `export const useEditorStore = create<EditorState>((set, get) => ({\n  tabs: [],\n  activeTabId: null,\n  // Added Agent Checkpoint engine\n  checkpointRef: 'refs/shark/checkpoints/latest',\n  rollbackTurn: () => { /* Instant 1-click turn revert */ },\n}));`,
      status: 'pending' as const,
    };
    setActiveDiff(diff);
  };

  return (
    <div className="flex flex-col h-full bg-[#18181b] border-l border-[#27272a] select-none w-80 shrink-0">
      {/* Top Header & Model Selector */}
      <div className="p-3 border-b border-[#27272a] flex items-center justify-between relative bg-[#1f1f23]/60">
        <div className="relative">
          <button
            onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
            className="flex items-center space-x-1.5 bg-[#27272a] hover:bg-[#3f3f46] text-xs text-zinc-100 font-medium px-2.5 py-1.5 rounded transition-colors"
          >
            <Sparkles size={13} className="text-blue-400" />
            <span className="truncate max-w-[140px]">{selectedModel.name}</span>
            <ChevronDown size={13} className="text-zinc-400" />
          </button>

          {modelDropdownOpen && (
            <div className="absolute left-0 mt-1 w-56 bg-[#27272a] border border-[#3f3f46] rounded-md shadow-xl py-1 z-50">
              <div className="px-2 py-1 text-[10px] font-semibold text-zinc-500 uppercase tracking-wider">
                Select Model (BYOK)
              </div>
              {AVAILABLE_MODELS.map((m) => (
                <button
                  key={m.id}
                  onClick={() => {
                    setSelectedModel(m);
                    setModelDropdownOpen(false);
                  }}
                  className={`w-full text-left px-2.5 py-1.5 text-xs hover:bg-blue-600 hover:text-white flex items-center justify-between transition-colors ${
                    m.id === selectedModel.id ? 'text-blue-400 font-semibold' : 'text-zinc-200'
                  }`}
                >
                  <span className="truncate">{m.name}</span>
                  <span className="text-[10px] opacity-60 ml-2 uppercase">{m.provider}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          onClick={clearHistory}
          title="Clear Conversation"
          className="p-1 hover:bg-[#27272a] rounded text-zinc-400 hover:text-white transition-colors"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {/* Quick Agent Actions */}
      <div className="flex items-center space-x-1 px-3 py-2 border-b border-[#27272a] overflow-x-auto bg-[#18181b] text-[11px]">
        <button
          onClick={handleInspectWorkspace}
          className="flex items-center space-x-1 bg-[#27272a] hover:bg-[#3f3f46] text-zinc-300 px-2 py-1 rounded shrink-0 transition-colors"
        >
          <Search size={11} className="text-blue-400" />
          <span>Inspect AST</span>
        </button>
        <button
          onClick={handleTriggerDiff}
          className="flex items-center space-x-1 bg-[#27272a] hover:bg-[#3f3f46] text-zinc-300 px-2 py-1 rounded shrink-0 transition-colors"
        >
          <GitCompare size={11} className="text-emerald-400" />
          <span>Demo Diff</span>
        </button>
        <button
          onClick={() => setInput('Run terminal command to test the application build.')}
          className="flex items-center space-x-1 bg-[#27272a] hover:bg-[#3f3f46] text-zinc-300 px-2 py-1 rounded shrink-0 transition-colors"
        >
          <Terminal size={11} className="text-purple-400" />
          <span>PTY Run</span>
        </button>
      </div>

      {/* Message History */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3" ref={scrollRef}>
        {messages.map((msg) => (
          <div key={msg.id} className="space-y-1.5 text-xs">
            <div className="flex items-center space-x-1.5 text-[11px] text-zinc-400">
              {msg.sender === 'user' ? (
                <>
                  <User size={13} className="text-zinc-300" />
                  <span className="font-semibold text-zinc-300">You</span>
                </>
              ) : (
                <>
                  <Bot size={13} className="text-blue-400" />
                  <span className="font-semibold text-blue-400">Shark Agent</span>
                </>
              )}
              <span className="text-zinc-600">{msg.timestamp}</span>
            </div>

            {/* Thinking block if present */}
            {msg.thinking && (
              <div className="bg-[#1f1f23] border border-[#27272a] rounded p-2 text-zinc-400 text-[11px] italic font-mono space-y-1">
                <div className="flex items-center space-x-1 text-zinc-500 font-sans not-italic">
                  <Sparkles size={11} className="text-amber-400" />
                  <span className="font-medium text-[10px] uppercase">Extended Thinking</span>
                </div>
                <div>{msg.thinking}</div>
              </div>
            )}

            {/* Tool Calls if present */}
            {msg.toolCalls && msg.toolCalls.length > 0 && (
              <div className="space-y-1">
                {msg.toolCalls.map((tc) => (
                  <div
                    key={tc.id}
                    className="flex items-center justify-between bg-[#27272a]/80 border border-[#3f3f46] rounded px-2 py-1 text-[11px]"
                  >
                    <div className="flex items-center space-x-1.5 text-zinc-300">
                      <Wrench size={11} className="text-purple-400" />
                      <span className="font-mono">{tc.name}</span>
                    </div>
                    <span
                      className={`text-[10px] px-1.5 py-0.2 rounded font-medium ${
                        tc.status === 'success'
                          ? 'bg-emerald-950 text-emerald-400'
                          : 'bg-blue-950 text-blue-400 animate-pulse'
                      }`}
                    >
                      {tc.status}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Message Body */}
            {msg.content && (
              <div
                className={`p-2.5 rounded-lg leading-relaxed ${
                  msg.sender === 'user'
                    ? 'bg-blue-600/20 border border-blue-500/30 text-zinc-100'
                    : 'bg-[#1f1f23] border border-[#27272a] text-zinc-200'
                }`}
              >
                {msg.content}
              </div>
            )}

            {/* Proposed Diffs */}
            {msg.proposedDiffs && msg.proposedDiffs.length > 0 && (
              <div className="space-y-1 pt-1">
                {msg.proposedDiffs.map((diff, idx) => (
                  <div
                    key={idx}
                    className="p-2 bg-amber-950/30 border border-amber-900/60 rounded flex items-center justify-between text-xs"
                  >
                    <div className="truncate max-w-[150px] font-mono text-[11px] text-amber-200">
                      {diff.filePath.split('/').pop()}
                    </div>
                    <button
                      onClick={() => setActiveDiff(diff)}
                      className="flex items-center space-x-1 bg-amber-600 hover:bg-amber-500 text-white px-2 py-0.5 rounded text-[11px] transition-colors"
                    >
                      <Eye size={11} />
                      <span>Review Diff</span>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Input Form */}
      <form onSubmit={handleSend} className="p-3 border-t border-[#27272a] bg-[#141416]">
        <div className="relative flex items-center bg-[#27272a] border border-[#3f3f46] rounded-md focus-within:border-blue-500 transition-colors">
          <textarea
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={`Instruct ${selectedModel.name} or type prompt...`}
            className="w-full bg-transparent outline-none p-2 text-xs text-zinc-100 placeholder-zinc-500 resize-none font-sans"
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            className={`mr-2 p-1.5 rounded transition-colors ${
              input.trim() && !isStreaming
                ? 'bg-blue-600 text-white hover:bg-blue-500'
                : 'text-zinc-600 cursor-not-allowed'
            }`}
          >
            <Send size={13} />
          </button>
        </div>
        <div className="flex items-center justify-between text-[10px] text-zinc-500 mt-1.5 px-0.5">
          <span>Enter to send, Shift+Enter for newline</span>
          <span className="text-emerald-400 font-mono">ACP Ready</span>
        </div>
      </form>
    </div>
  );
};
