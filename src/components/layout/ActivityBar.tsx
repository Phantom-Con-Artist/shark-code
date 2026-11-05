import React from 'react';
import { Files, Search, Bot, Terminal, Settings } from 'lucide-react';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

export const ActivityBar: React.FC = () => {
  const { activeActivity, setActiveActivity } = useWorkspaceStore();

  const activities = [
    { id: 'explorer' as const, icon: Files, label: 'Explorer (Ctrl+Shift+E)' },
    { id: 'search' as const, icon: Search, label: 'Search (Ctrl+Shift+F)' },
    { id: 'agent' as const, icon: Bot, label: 'Shark Agent (Ctrl+Shift+A)' },
    { id: 'terminal' as const, icon: Terminal, label: 'Terminal (Ctrl+`)' },
  ];

  return (
    <div className="w-12 bg-[#18181b] border-r border-[#27272a] flex flex-col justify-between items-center py-2 select-none z-20">
      <div className="flex flex-col items-center space-y-1 w-full">
        {activities.map((item) => {
          const Icon = item.icon;
          const isActive = activeActivity === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveActivity(item.id)}
              title={item.label}
              className={`relative w-10 h-10 flex items-center justify-center rounded-md transition-all ${
                isActive
                  ? 'text-blue-400 bg-[#27272a]'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-[#27272a]/50'
              }`}
            >
              {isActive && (
                <div className="absolute left-0 w-0.5 h-6 bg-blue-500 rounded-r" />
              )}
              <Icon size={20} strokeWidth={isActive ? 2.2 : 1.8} />
            </button>
          );
        })}
      </div>

      <div className="flex flex-col items-center space-y-1 w-full">
        <button
          onClick={() => setActiveActivity('settings')}
          title="Settings & BYOK Keys"
          className={`relative w-10 h-10 flex items-center justify-center rounded-md transition-all ${
            activeActivity === 'settings'
              ? 'text-blue-400 bg-[#27272a]'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-[#27272a]/50'
          }`}
        >
          {activeActivity === 'settings' && (
            <div className="absolute left-0 w-0.5 h-6 bg-blue-500 rounded-r" />
          )}
          <Settings size={20} strokeWidth={1.8} />
        </button>
      </div>
    </div>
  );
};
