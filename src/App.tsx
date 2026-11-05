import { Tooltips } from './components/workbench/NativeUi';
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import './App.css';
import { Workbench } from './components/workbench/Workbench';

export default function App() {
  return <><Workbench /><Tooltips /></>;
}
