import { create } from 'zustand';
export type DialogOptions = { title: string; message: string; confirmLabel?: string; danger?: boolean; input?: {label: string; value: string} };
type DialogRequest = DialogOptions & {id: number; resolve(value: string | null): void};
export const useDialogs = create<{active: DialogRequest | null; queue: DialogRequest[]}>()(() => ({active: null, queue: []}));
let sequence = 0;
function request(options: DialogOptions): Promise<string | null> {
  return new Promise(resolve => {
    const item = {...options, id: ++sequence, resolve};
    useDialogs.setState(s => s.active ? {queue: [...s.queue, item]} : {active: item});
  });
}
export async function confirmAction(options: DialogOptions): Promise<boolean> { return await request(options) !== null; }
export function promptValue(options: DialogOptions & {input: {label: string; value: string}}): Promise<string | null> { return request(options); }
export function settleDialog(value: string | null) {
  const s = useDialogs.getState();
  if (!s.active) return;
  useDialogs.setState({active: s.queue[0] ?? null, queue: s.queue.slice(1)});
  s.active.resolve(value);
}
