import { create } from 'zustand';
import { persist } from 'zustand/middleware';
export interface ReadingPreferences {
  density: 'compact' | 'comfortable'; fontSize: number; readingFont: 'system' | 'readable';
  highContrast: boolean; reduceMotion: boolean; model: string;
  set: (patch: Partial<Omit<ReadingPreferences, 'set'>>) => void;
}
export const useReadingPreferences = create<ReadingPreferences>()(persist(set => ({
  density: 'compact', fontSize: 13, readingFont: 'system', highContrast: false,
  reduceMotion: true, model: '', set: patch => set(patch),
}), { name: 'shark.reading-preferences.v1' }));
