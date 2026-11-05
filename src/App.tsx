import React, { useState } from 'react';
import { ActivityBar } from '@/components/layout/ActivityBar';
import { StatusBar } from '@/components/layout/StatusBar';
import { FileExplorer } from '@/components/sidebar/FileExplorer';
import { SearchPanel } from '@/components/sidebar/SearchPanel';
import { SettingsModal } from '@/components/sidebar/SettingsModal';
import { EditorArea } from '@/components/editor/EditorArea';
import { TerminalPanel } from '@/components/terminal/TerminalPanel';
import { AgentSidebar } from '@/components/agent/AgentSidebar';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

export const App: React.FC = () => {
  const { activeActivity } = useWorkspaceStore();
  const [terminalOpen, setTerminalOpen] = useState(true);
  const [agentSidebarOpen, setAgentSidebarOpen] = useState(true);

  // If user clicks terminal on activity bar, toggle terminal panel
  const handleActivityClick = () => {
    if (activeActivity === 'terminal') {
      setTerminalOpen(!terminalOpen);
    } else if (activeActivity === 'agent') {
      setAgentSidebarOpen(!agentSidebarOpen);
    }
  };

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[#18181b] text-zinc-100 font-sans">
      {/* Main Workspace Row */}
      <div className="flex flex-1 overflow-hidden" onClick={handleActivityClick}>
        {/* Leftmost Activity Bar */}
        <ActivityBar />

        {/* Dynamic Left Sidebar */}
        {activeActivity !== 'terminal' && activeActivity !== 'agent' && (
          <div className="w-64 h-full shrink-0">
            {activeActivity === 'explorer' && <FileExplorer />}
            {activeActivity === 'search' && <SearchPanel />}
            {activeActivity === 'settings' && <SettingsModal />}
          </div>
        )}

        {/* Center: Editor & Terminal */}
        <div className="flex-1 flex flex-col h-full overflow-hidden">
          <EditorArea />
          {terminalOpen && <TerminalPanel onClose={() => setTerminalOpen(false)} />}
        </div>

        {/* Right: Agent-First Sidebar */}
        {agentSidebarOpen && <AgentSidebar />}
      </div>

      {/* Bottom Status Bar */}
      <StatusBar />
    </div>
  );
};

export default App;
