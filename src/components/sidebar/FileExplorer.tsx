import React, { useState } from 'react';
import {
  ChevronRight,
  ChevronDown,
  Folder,
  FolderOpen,
  FileCode,
  FileText,
  FileJson,
  Plus,
  RefreshCw,
} from 'lucide-react';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useEditorStore } from '@/stores/useEditorStore';
import { FileNode } from '@/types';

// Mock initial tree if not connected to backend yet
const DEFAULT_TREE: FileNode[] = [
  {
    name: 'src',
    path: '/home/subhradeep/Development/shark code/src',
    isDirectory: true,
    children: [
      {
        name: 'components',
        path: '/home/subhradeep/Development/shark code/src/components',
        isDirectory: true,
        children: [
          { name: 'App.tsx', path: '/home/subhradeep/Development/shark code/src/App.tsx', isDirectory: false },
          { name: 'main.tsx', path: '/home/subhradeep/Development/shark code/src/main.tsx', isDirectory: false },
        ],
      },
      {
        name: 'stores',
        path: '/home/subhradeep/Development/shark code/src/stores',
        isDirectory: true,
        children: [
          { name: 'useEditorStore.ts', path: '/home/subhradeep/Development/shark code/src/stores/useEditorStore.ts', isDirectory: false },
          { name: 'useAgentStore.ts', path: '/home/subhradeep/Development/shark code/src/stores/useAgentStore.ts', isDirectory: false },
        ],
      },
      { name: 'types.ts', path: '/home/subhradeep/Development/shark code/src/types/index.ts', isDirectory: false },
    ],
  },
  {
    name: 'src-tauri',
    path: '/home/subhradeep/Development/shark code/src-tauri',
    isDirectory: true,
    children: [
      { name: 'Cargo.toml', path: '/home/subhradeep/Development/shark code/src-tauri/Cargo.toml', isDirectory: false },
      { name: 'tauri.conf.json', path: '/home/subhradeep/Development/shark code/src-tauri/tauri.conf.json', isDirectory: false },
    ],
  },
  { name: 'package.json', path: '/home/subhradeep/Development/shark code/package.json', isDirectory: false },
  { name: 'README.md', path: '/home/subhradeep/Development/shark code/README.md', isDirectory: false },
];

function getFileIcon(fileName: string) {
  if (fileName.endsWith('.tsx') || fileName.endsWith('.ts') || fileName.endsWith('.js') || fileName.endsWith('.rs')) {
    return <FileCode size={15} className="text-blue-400 shrink-0" />;
  }
  if (fileName.endsWith('.json')) {
    return <FileJson size={15} className="text-yellow-400 shrink-0" />;
  }
  return <FileText size={15} className="text-zinc-400 shrink-0" />;
}

interface TreeItemProps {
  node: FileNode;
  level: number;
}

const TreeItem: React.FC<TreeItemProps> = ({ node, level }) => {
  const { expandedPaths, toggleFolder } = useWorkspaceStore();
  const { openTab } = useEditorStore();
  const isExpanded = expandedPaths.has(node.path);

  const handleClick = () => {
    if (node.isDirectory) {
      toggleFolder(node.path);
    } else {
      openTab({
        path: node.path,
        name: node.name,
        content: `// Content of ${node.name}\n// Loaded from Shark Code workspace\n`,
        language: node.name.split('.').pop() || 'plaintext',
      });
    }
  };

  return (
    <div>
      <div
        onClick={handleClick}
        style={{ paddingLeft: `${level * 14 + 10}px` }}
        className="flex items-center space-x-1.5 py-1 px-2 hover:bg-[#27272a] text-zinc-300 hover:text-white cursor-pointer text-xs select-none rounded-sm transition-colors group"
      >
        {node.isDirectory ? (
          <>
            <span className="text-zinc-500 group-hover:text-zinc-300">
              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </span>
            {isExpanded ? (
              <FolderOpen size={15} className="text-amber-400 shrink-0" />
            ) : (
              <Folder size={15} className="text-amber-400 shrink-0" />
            )}
            <span className="font-medium truncate">{node.name}</span>
          </>
        ) : (
          <>
            <span className="w-3.5" />
            {getFileIcon(node.name)}
            <span className="truncate">{node.name}</span>
          </>
        )}
      </div>

      {node.isDirectory && isExpanded && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeItem key={child.path} node={child} level={level + 1} />
          ))}
        </div>
      )}
    </div>
  );
};

export const FileExplorer: React.FC = () => {
  const { projectName, fileTree } = useWorkspaceStore();
  const [tree] = useState<FileNode[]>(fileTree.length > 0 ? fileTree : DEFAULT_TREE);

  return (
    <div className="flex flex-col h-full bg-[#18181b] border-r border-[#27272a] select-none">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#27272a] text-xs font-semibold uppercase tracking-wider text-zinc-400">
        <span className="truncate">{projectName}</span>
        <div className="flex items-center space-x-1">
          <button className="p-1 hover:bg-[#27272a] rounded text-zinc-400 hover:text-white" title="New File">
            <Plus size={14} />
          </button>
          <button className="p-1 hover:bg-[#27272a] rounded text-zinc-400 hover:text-white" title="Refresh">
            <RefreshCw size={13} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {tree.map((node) => (
          <TreeItem key={node.path} node={node} level={0} />
        ))}
      </div>
    </div>
  );
};
