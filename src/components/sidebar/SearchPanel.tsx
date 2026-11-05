import React, { useState } from 'react';
import { Search as SearchIcon, CaseSensitive, WholeWord, Regex } from 'lucide-react';
import { useEditorStore } from '@/stores/useEditorStore';
import { SearchResult } from '@/types';

export const SearchPanel: React.FC = () => {
  const [query, setQuery] = useState('');
  const [isCaseSensitive, setIsCaseSensitive] = useState(false);
  const [isWholeWord, setIsWholeWord] = useState(false);
  const [isRegex, setIsRegex] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const { openTab } = useEditorStore();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    // Fast mock search results for preview (hooked to Tauri Ripgrep backend)
    setResults([
      {
        filePath: '/home/subhradeep/Development/shark code/src/stores/useAgentStore.ts',
        lineNumber: 12,
        lineContent: `export const useAgentStore = create<AgentState>((set) => ({`,
        matchStart: 13,
        matchEnd: 26,
      },
      {
        filePath: '/home/subhradeep/Development/shark code/src/types/index.ts',
        lineNumber: 22,
        lineContent: `export interface AgentMessage {`,
        matchStart: 17,
        matchEnd: 29,
      },
    ]);
  };

  const handleResultClick = (res: SearchResult) => {
    const fileName = res.filePath.split('/').pop() || 'file';
    openTab({
      path: res.filePath,
      name: fileName,
      content: `// Sample content from ${fileName}\n\nLine ${res.lineNumber}: ${res.lineContent}\n`,
      language: fileName.split('.').pop() || 'plaintext',
      cursorPosition: { line: res.lineNumber, column: res.matchStart },
    });
  };

  return (
    <div className="flex flex-col h-full bg-[#18181b] border-r border-[#27272a] select-none p-3">
      <div className="text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-2">
        Search Workspace
      </div>

      <form onSubmit={handleSearch} className="relative mb-3">
        <div className="flex items-center bg-[#27272a] border border-[#3f3f46] rounded px-2 py-1 text-sm text-zinc-200 focus-within:border-blue-500">
          <SearchIcon size={14} className="text-zinc-400 mr-2 shrink-0" />
          <input
            type="text"
            placeholder="Search files (Ripgrep)..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full bg-transparent outline-none text-xs text-zinc-100 placeholder-zinc-500"
          />
          <div className="flex items-center space-x-1 shrink-0 ml-1">
            <button
              type="button"
              onClick={() => setIsCaseSensitive(!isCaseSensitive)}
              className={`p-0.5 rounded text-xs ${isCaseSensitive ? 'bg-blue-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
              title="Match Case"
            >
              <CaseSensitive size={13} />
            </button>
            <button
              type="button"
              onClick={() => setIsWholeWord(!isWholeWord)}
              className={`p-0.5 rounded text-xs ${isWholeWord ? 'bg-blue-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
              title="Match Whole Word"
            >
              <WholeWord size={13} />
            </button>
            <button
              type="button"
              onClick={() => setIsRegex(!isRegex)}
              className={`p-0.5 rounded text-xs ${isRegex ? 'bg-blue-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
              title="Use Regular Expression"
            >
              <Regex size={13} />
            </button>
          </div>
        </div>
      </form>

      <div className="flex-1 overflow-y-auto">
        {results.length > 0 ? (
          <div className="space-y-2">
            <div className="text-[11px] text-zinc-500">
              {results.length} results found
            </div>
            {results.map((res, i) => (
              <div
                key={i}
                onClick={() => handleResultClick(res)}
                className="p-2 rounded bg-[#1f1f23] hover:bg-[#27272a] cursor-pointer text-xs transition-colors border border-transparent hover:border-[#3f3f46]"
              >
                <div className="text-blue-400 font-mono text-[11px] truncate mb-0.5">
                  {res.filePath.split('/').pop()} : {res.lineNumber}
                </div>
                <div className="text-zinc-300 font-mono text-[11px] truncate bg-[#18181b] px-1.5 py-0.5 rounded">
                  {res.lineContent}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-zinc-500 italic text-center py-6">
            Type a query and press Enter to search across the entire project.
          </div>
        )}
      </div>
    </div>
  );
};
