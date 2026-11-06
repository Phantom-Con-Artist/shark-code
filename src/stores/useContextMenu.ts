import { create } from 'zustand';
export type ContextItem = {label: string; shortcut?: string; danger?: boolean; disabled?: boolean; run(): void | Promise<void>} | 'separator';
export const useContextMenu = create<{menu: {x: number; y: number; items: ContextItem[]} | null}>()(() => ({menu: null}));
export function showContextMenu(x: number, y: number, items: ContextItem[]) { useContextMenu.setState({menu: {x,y,items}}); }
export function closeContextMenu() { useContextMenu.setState({menu: null}); }
