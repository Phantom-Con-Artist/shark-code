import { useSettings } from '../stores/useSettings';
import { useUi } from '../stores/useUi';

export function openWorkbenchBrowser(address?: string) {
  const s = useSettings.getState();
  s.set({view: 'code', editorOpen: true, ...(s.sidebarView === 'browser' ? {sidebarView: 'files' as const} : {}), ...(address !== undefined ? {browserUrl: address} : {})});
  useUi.getState().set({editorView: 'browser'});
}
export function toggleWorkbenchBrowser() {
  const u = useUi.getState();
  if (u.editorView === 'browser') u.set({editorView: 'file', browserWide: false});
  else openWorkbenchBrowser();
}
