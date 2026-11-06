import { Tooltips } from './components/workbench/NativeUi';
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import './App.css';
import { Workbench } from './components/workbench/Workbench';
import { AppDialogs } from './components/workbench/AppDialogs';
import { useDialogs } from './stores/useDialogs';
import { ContextMenus } from './components/workbench/ContextMenus';

export default function App() {
  const dialog = useDialogs(s => s.active);
  return <><div inert={!!dialog || undefined}><Workbench /></div><Tooltips /><ContextMenus /><AppDialogs /></>;
}
