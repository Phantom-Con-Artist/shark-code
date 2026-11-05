import React from 'react';
import { GitBranch, CheckCircle2, Cpu, Sparkles } from 'lucide-react';
import { useEditorStore } from '@/stores/useEditorStore';
import { useAgentStore } from '@/stores/useAgentStore';

export const StatusBar: React.FC = () => {
  const { tabs, activeTabId, cursorPosition } = useEditorStore();
  const { selectedModel, isStreaming } = useAgentStore();

  const activeTab = tabs.find((t) => t.id === activeTabId);

  return (
    <div className="h-6 bg-[#18181b] border-t border-[#27272a] text-xs text-zinc-400 px-3 flex items-center justify-between select-none z-20">
      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-1 hover:text-zinc-200 cursor-pointer">
          <GitBranch size={13} className="text-blue-400" />
          <span>main</span>
        </div>

        <div className="flex items-center space-x-1">
          <CheckCircle2 size={13} className="text-emerald-400" />
          <span>0 errors, 0 warnings</span>
        </div>
      </div>

      <div className="flex items-center space-x-4">
        {isStreaming && (
          <div className="flex items-center space-x-1.5 text-blue-400 animate-pulse">
            <Sparkles size={12} />
            <span>Agent thinking...</span>
          </div>
        )}

        <div className="flex items-center space-x-1 bg-[#27272a] px-2 py-0.5 rounded text-zinc-300">
          <Cpu size={12} className="text-purple-400" />
          <span>{selectedModel.name}</span>
        </div>

        {activeTab && (
          <div className="flex items-center space-x-3">
            <span>
              Ln {cursorPosition.line}, Col {cursorPosition.column}
            </span>
            <span>UTF-8</span>
            <span className="capitalize">{activeTab.language}</span>
          </div>
        )}
      </div>
    </div>
  );
};
