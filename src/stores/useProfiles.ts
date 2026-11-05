import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Profile = { id: string; name: string; color: string; created: number };
const COLORS = ['oklch(0.72 0.12 230)', 'oklch(0.74 0.13 160)', 'oklch(0.76 0.12 75)', 'oklch(0.7 0.14 25)', 'oklch(0.7 0.12 300)', 'oklch(0.72 0.1 200)'];
const KEY = 'shark.profiles.v1';

/** Active profile id, read synchronously so per-profile stores can pick their storage key at startup. */
export function activeProfileId(): string {
  try { return JSON.parse(localStorage.getItem(KEY) || '{}')?.state?.active || 'default'; } catch { return 'default'; }
}

interface Profiles {
  profiles: Profile[]; active: string;
  create(name: string): string; rename(id: string, name: string): void; remove(id: string): void; switchTo(id: string): void;
}
export const useProfiles = create<Profiles>()(persist((set, get) => ({
  profiles: [{ id: 'default', name: 'Default', color: COLORS[0], created: 0 }], active: 'default',
  create: name => {
    const id = Math.random().toString(36).slice(2, 10);
    set(s => ({ profiles: [...s.profiles, { id, name: name.trim() || 'Profile', color: COLORS[s.profiles.length % COLORS.length], created: Date.now() }] }));
    return id;
  },
  rename: (id, name) => set(s => ({ profiles: s.profiles.map(p => p.id === id ? { ...p, name: name.trim() || p.name } : p) })),
  remove: id => {
    if (id === 'default') return;
    try { localStorage.removeItem(`shark.settings.v3.${id}`); } catch { /* storage unavailable */ }
    set(s => ({ profiles: s.profiles.filter(p => p.id !== id) }));
    if (get().active === id) get().switchTo('default');
  },
  // Every profile has separate settings, layout, agent choice and keys; switching reloads into it.
  switchTo: id => { set({ active: id }); setTimeout(() => location.reload(), 30); },
}), { name: KEY }));
