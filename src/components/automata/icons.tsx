import {
  Activity, Box, Braces, CheckCircle2, Code2, Compass, Cpu, File, FilePen, Gauge,
  GitBranch, Globe, History, Layers, List, Merge, MessageSquare, OctagonAlert,
  Play, Puzzle, Radar, Search, ShieldCheck, Sparkles, Split, Terminal, Timer, Type,
} from 'lucide-react';

const ICONS = {
  play: Play, braces: Braces, type: Type, list: List, code: Code2, split: Split, merge: Merge,
  timer: Timer, octagon: OctagonAlert, globe: Globe, file: File, 'file-pen': FilePen,
  terminal: Terminal, shield: ShieldCheck, message: MessageSquare, sparkles: Sparkles,
  puzzle: Puzzle, box: Box, layers: Layers, 'git-branch': GitBranch, search: Search,
  radar: Radar, gauge: Gauge, activity: Activity, compass: Compass, history: History,
  cpu: Cpu, 'check-circle': CheckCircle2,
} as const;

export function ComponentIcon({ name, size = 14 }: { name: string; size?: number }) {
  const Icon = (ICONS as Record<string, typeof Box>)[name] ?? Box;
  return <Icon size={size} strokeWidth={1.7} />;
}
