import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { activeProfileId } from './useProfiles';

export type ProviderId = 'claude-code' | 'codex' | 'muse' | 'antigravity' | 'anthropic' | 'gemini' | 'openrouter';
export const CLI_ORDER: ProviderId[] = ['claude-code', 'codex', 'antigravity', 'muse'];
export const API_ORDER: ProviderId[] = ['openrouter', 'anthropic', 'gemini'];
export type Theme = 'system' | 'light' | 'dark';
export type ModeId = 'builder' | 'debugger' | 'review' | 'planner' | 'explain' | 'tests' | 'refactor';
export const MODES: { id: ModeId; label: string; hint: string; readOnly: boolean }[] = [
  { id: 'builder', label: 'Builder', hint: 'Implements the request end to end', readOnly: false },
  { id: 'debugger', label: 'Debugger', hint: 'Root cause first, then the minimal fix', readOnly: false },
  { id: 'review', label: 'Adversarial review', hint: 'Hunts for real defects · read-only', readOnly: true },
  { id: 'planner', label: 'Planner', hint: 'Step-by-step plan · read-only', readOnly: true },
  { id: 'explain', label: 'Explain', hint: 'Walks through how code works · read-only', readOnly: true },
  { id: 'tests', label: 'Test writer', hint: 'Only touches test files', readOnly: false },
  { id: 'refactor', label: 'Refactor', hint: 'Restructures without changing behaviour', readOnly: false },
];
export const BUILTIN_SKILLS: { id: string; label: string; hint: string }[] = [
  { id: 'caveman', label: 'Caveman', hint: 'Short blunt words. Code stays normal.' },
  { id: 'concise', label: 'Concise', hint: 'Terse, bullets, no recap' },
  { id: 'teacher', label: 'Teacher', hint: 'Explains the why for newer devs' },
  { id: 'senior', label: 'Senior engineer', hint: 'Trade-offs and risks up front' },
];
export type CustomSkill = { id: string; name: string; text: string };
export type Effort = '' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
export const EFFORTS: { id: Effort; label: string }[] = [{ id: '', label: 'Default' }, { id: 'low', label: 'Low' }, { id: 'medium', label: 'Medium' }, { id: 'high', label: 'High' }, { id: 'xhigh', label: 'Extra high' }, { id: 'max', label: 'Max' }];

export const PROVIDERS: Record<ProviderId, { label: string; kind: 'byok' | 'cli'; hint: string; models: string[]; keyEnv?: string; keyUrl?: string }> = {
  'claude-code': { label: 'Claude Code', kind: 'cli', hint: 'Uses your signed-in Claude CLI', models: ['', 'opus', 'sonnet', 'haiku'] },
  codex: { label: 'Codex', kind: 'cli', hint: 'Uses your signed-in Codex CLI', models: [''] },
  muse: { label: 'Muse', kind: 'cli', hint: 'Uses your signed-in Muse CLI', models: [''] },
  antigravity: { label: 'Antigravity', kind: 'cli', hint: 'Uses your signed-in agy CLI', models: ['', 'gemini-3.8-flash-medium', 'gemini-3.8-flash-high', 'claude-opus-4-6-thinking', 'claude-sonnet-4-6'] },
  anthropic: { label: 'Anthropic', kind: 'byok', hint: 'Your Anthropic API key', models: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'], keyEnv: 'ANTHROPIC_API_KEY', keyUrl: 'console.anthropic.com' },
  openrouter: { label: 'OpenRouter', kind: 'byok', hint: 'One key for hundreds of models', models: ['anthropic/claude-sonnet-5.5', 'anthropic/claude-opus-5.5', 'google/gemini-3.8-flash', 'deepseek/deepseek-v4.1-flash', 'qwen/qwen3-coder'], keyEnv: 'OPENROUTER_API_KEY', keyUrl: 'openrouter.ai/keys' },
  gemini: { label: 'Gemini', kind: 'byok', hint: 'Your Google AI Studio key', models: ['gemini-2.5-pro', 'gemini-2.5-flash'], keyEnv: 'GEMINI_API_KEY', keyUrl: 'aistudio.google.com' },
};

export interface Settings {
  theme: Theme; density: 'compact' | 'comfortable'; fontSize: number; editorFontSize: number;
  readingFont: 'default' | 'readable'; highContrast: boolean; reduceMotion: boolean;
  wordWrap: boolean; minimap: boolean;
  sidebarOpen: boolean; editorOpen: boolean; terminalOpen: boolean;
  sidebarWidth: number; editorWidth: number; terminalHeight: number; sidebarView: 'sessions' | 'files' | 'search' | 'scm' | 'run' | 'browser' | 'plugins' | `plugin:${string}`;
  provider: ProviderId; models: Record<ProviderId, string>; efforts: Partial<Record<ProviderId, Effort>>; keys: Partial<Record<ProviderId, string>>;
  attachActiveFile: boolean; browserUrl: string; disabledPlugins: string[];
  view: 'shark' | 'code'; agentWidth: number; mode: ModeId; skills: string[]; customSkills: CustomSkill[]; activeCustomSkills: string[];
  set(patch: Partial<Omit<Settings, 'set' | 'toggle'>>): void;
  toggle(key: 'sidebarOpen' | 'editorOpen' | 'terminalOpen'): void;
}

export const LAYOUT_DEFAULTS = { sidebarWidth: 248, editorWidth: 640, terminalHeight: 240 };

export const useSettings = create<Settings>()(persist(set => ({
  theme: 'system', density: 'compact', fontSize: 13, editorFontSize: 13, readingFont: 'default',
  highContrast: false, reduceMotion: false, wordWrap: true, minimap: false,
  sidebarOpen: true, editorOpen: false, terminalOpen: false, sidebarView: 'files',
  ...LAYOUT_DEFAULTS,
  provider: 'claude-code', efforts: {}, models: { 'claude-code': '', codex: '', muse: '', antigravity: '', anthropic: 'claude-sonnet-5-5', gemini: 'gemini-2.5-pro', openrouter: 'anthropic/claude-sonnet-5.5' }, keys: {},
  attachActiveFile: true, browserUrl: 'http://localhost:5173', disabledPlugins: [],
  view: 'shark', agentWidth: 420, mode: 'builder', skills: [], customSkills: [], activeCustomSkills: [],
  set: patch => set(patch),
  toggle: key => set(s => ({ [key]: !s[key] }) as Partial<Settings>),
}), { name: `shark.settings.v3.${activeProfileId()}`, version: 1 }));

export function resolvedTheme(theme: Theme): 'light' | 'dark' {
  if (theme !== 'system') return theme;
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}
