import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { closeContextMenu, showContextMenu, useContextMenu, type ContextItem } from '../../stores/useContextMenu';
import { confirmAction, promptValue, useDialogs } from '../../stores/useDialogs';
import { useProjectStore } from '../../stores/useProjectStore';
import { useSettings } from '../../stores/useSettings';
import { useUi } from '../../stores/useUi';
import { useGit } from '../../stores/useGit';
import { openPath } from './Sidebar';
import { askAgent } from './BottomPanel';
import { closeTab } from './EditorArea';

const parent = (path: string) => path.split('/').slice(0,-1).join('/');
const join = (dir: string, name: string) => dir ? dir + '/' + name : name;
let fileClipboard: {root: string; path: string; cut: boolean} | null = null;
export async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {try {await navigator.clipboard.writeText(value); return;} catch { /* WebKit clipboard fallback */ }}
  const input=document.createElement('textarea'); input.value=value; input.style.cssText='position:fixed;left:-9999px'; document.body.append(input); input.select();
  const copied=document.execCommand('copy'); input.remove();
  if (!copied) throw Error('Clipboard access is unavailable.');
}
async function createEntry(dir: string, folder: boolean) {
  const path=await promptValue({title: folder ? 'New folder' : 'New file', message: `Create inside ${dir || 'the project root'}.`, confirmLabel: 'Create', input:{label:'Relative path',value:dir ? dir+'/' : ''}});
  if (!path) return;
  if (folder) await useProjectStore.getState().mutatePath('mkdir',path);
  else {await useProjectStore.getState().createFile(path); useUi.getState().set({editorView:'file'});}
}
async function renameEntry(path: string) {
  const to=await promptValue({title:'Rename',message:'Choose a new path inside this project.',confirmLabel:'Rename',input:{label:'Relative path',value:path}});
  if (to && to!==path) {await useProjectStore.getState().mutatePath('rename',path,to); await useGit.getState().refresh();}
}
async function trashEntry(path: string) {
  const dirty=useProjectStore.getState().tabs.filter(t=>(t.path===path||t.path.startsWith(path+'/'))&&t.content!==t.saved).length;
  if (!await confirmAction({title:'Move to Trash?',message:`Move “${path}” to the system Trash?${dirty ? `\n\n${dirty} open file(s) have unsaved edits that will be discarded.` : ''}`,confirmLabel:'Move to Trash',danger:true})) return;
  await useProjectStore.getState().mutatePath('trash',path); await useGit.getState().refresh();
}
async function pasteEntry(dir: string) {
  const clipboard=fileClipboard, p=useProjectStore.getState();
  if (!clipboard || clipboard.root!==p.root) return;
  let destination=join(dir,clipboard.path.split('/').pop()!);
  if (p.entries.some(e=>e.path===destination)) {
    const newPath=await promptValue({title:'Paste as',message:'That name already exists. Choose another path.',confirmLabel:'Paste',input:{label:'Relative path',value:destination}});
    if (!newPath) return; destination=newPath;
  }
  await p.mutatePath(clipboard.cut?'rename':'copy',clipboard.path,destination);
  if (clipboard.cut && !useProjectStore.getState().error) fileClipboard=null;
}
function fileItems(path: string, directory: boolean): ContextItem[] {
  const p=useProjectStore.getState(), dir=directory?path:parent(path), native=p.kind==='native';
  const full=p.root.replace(/\/$/,'')+(path?'/'+path:'');
  return [
    ...(!directory ? [{label:'Open',run:()=>openPath(path)},{label:'Open in code workbench',run:()=>{openPath(path); useSettings.getState().set({view:'code',editorOpen:true});}}] : []),
    {label:'New File…',run:()=>createEntry(dir,false)},
    {label:'New Folder…',disabled:!native,run:()=>createEntry(dir,true)}, 'separator',
    {label:'Reveal in file manager',disabled:!native,run:async()=>{const {revealItemInDir}=await import('@tauri-apps/plugin-opener'); await revealItemInDir(full);}},
    {label:'Open in integrated terminal',disabled:!native,run:async()=>{const {runInTerminal}=await import('./Terminal');useSettings.getState().set({terminalOpen:true});useUi.getState().set({panelTab:'terminal'});runInTerminal('cd -- '+"'"+(p.root+(dir?'/'+dir:'')).replace(/'/g,"'\\''")+"'");}},
    {label:directory?'Add Folder to Chat':'Add File to Chat',run:()=>{askAgent(`Use ${directory?'the folder':'the file'} ${path || '.'} as context.\n\n`);useSettings.getState().set({editorOpen:true});useUi.getState().set({composerFocus:Date.now()});}},
    ...(directory?[]:[{label:'Ask Shark to explain',run:()=>askAgent(`Explain ${path}, using its current source and relevant dependencies.`)}]),
    'separator',
    ...(path?[{label:'Cut',shortcut:'Ctrl X',disabled:!native,run:()=>{fileClipboard={root:p.root,path,cut:true};}},{label:'Copy',shortcut:'Ctrl C',disabled:!native,run:()=>{fileClipboard={root:p.root,path,cut:false};}}]:[]),
    {label:'Paste',shortcut:'Ctrl V',disabled:!native||!fileClipboard||fileClipboard.root!==p.root,run:()=>pasteEntry(dir)},
    {label:'Copy Path',run:()=>copyText(full)}, {label:'Copy Relative Path',run:()=>copyText(path||'.')},
    ...(path?['separator' as const,{label:'Rename…',shortcut:'F2',disabled:!native,run:()=>renameEntry(path)},{label:'Move to Trash…',shortcut:'Del',danger:true,disabled:!native,run:()=>trashEntry(path)}]:[]),
    'separator', {label:'Refresh Explorer',run:()=>p.refresh()},
  ];
}
export function ContextMenus() {
  const menu=useContextMenu(s=>s.menu);
  const ref=useRef<HTMLDivElement>(null);
  const [position,setPosition]=useState({left:0,top:0});
  const previous=useRef<HTMLElement|null>(null);
  useEffect(()=>{
    const open=(event:MouseEvent)=>{
      event.preventDefault();
      const target=event.target as HTMLElement;
      if (target.closest('.monaco-editor')) return;
      const row=target.closest<HTMLElement>('.tree-row[data-path], [data-file-path]');
      const input=target.closest<HTMLInputElement|HTMLTextAreaElement>('input,textarea');
      const terminal=target.closest<HTMLElement>('[data-terminal-id]');
      let items:ContextItem[];
      if (input) {
        const selection=input.value.slice(input.selectionStart??0,input.selectionEnd??0);
        const writable=!input.readOnly&&!input.disabled;
        const insert=(value:string)=>{input.focus();document.execCommand('insertText',false,value);};
        items=[{label:'Cut',shortcut:'Ctrl X',disabled:!writable||!selection,run:async()=>{await copyText(selection);insert('');}},{label:'Copy',shortcut:'Ctrl C',disabled:!selection,run:()=>copyText(selection)},{label:'Paste',shortcut:'Ctrl V',disabled:!writable,run:async()=>insert(await navigator.clipboard.readText())},'separator',{label:'Select All',shortcut:'Ctrl A',run:()=>{input.focus();input.select();}}];
      } else if (row) {
        row.focus(); items=fileItems(row.dataset.path??row.dataset.filePath!,row.dataset.dir==='true');
        if (row.hasAttribute('data-file-path')) items.unshift({label:'Close tab',run:()=>closeTab(row.dataset.filePath!)},'separator');
      } else if (terminal) {
        const id=terminal.dataset.terminalId!;
        items=[{label:'Copy selection',run:async()=>{const {terminalSelection}=await import('./Terminal');await copyText(terminalSelection(id));}},{label:'Paste',run:async()=>{const {pasteTerminal}=await import('./Terminal');pasteTerminal(await navigator.clipboard.readText(),id);}},'separator',{label:'Select All',run:async()=>{const {selectTerminal}=await import('./Terminal');selectTerminal(id);}},{label:'Clear terminal',run:async()=>{const {clearTerminal}=await import('./Terminal');clearTerminal(id);}}];
      } else if (target.closest('.explorer')) items=fileItems('',true);
      else {
        const selection=window.getSelection()?.toString()??'';
        items=[{label:'Copy selection',disabled:!selection,run:()=>copyText(selection)},'separator',{label:'Command Palette',shortcut:'Ctrl K',run:()=>useUi.getState().open('palette')},{label:'Settings',shortcut:'Ctrl ,',run:()=>useUi.getState().open('settings')}];
      }
      const r=target.getBoundingClientRect();showContextMenu(event.clientX||r.left+12,event.clientY||r.top+12,items);
    };
    const key=(event:KeyboardEvent)=>{
      if (useDialogs.getState().active || useContextMenu.getState().menu) return;
      const row=(event.target as HTMLElement).closest<HTMLElement>('.tree-row[data-path]');
      if ((event.shiftKey&&event.key==='F10')||event.key==='ContextMenu') {event.preventDefault(); const el=event.target as HTMLElement;const r=el.getBoundingClientRect();el.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:r.left+12,clientY:r.top+12}));}
      else if (row&&event.key==='F2') {event.preventDefault();void renameEntry(row.dataset.path!);}
      else if (row&&event.key==='Delete') {event.preventDefault();void trashEntry(row.dataset.path!);}
      else if (row&&(event.ctrlKey||event.metaKey)&&['c','x','v'].includes(event.key.toLowerCase())) {event.preventDefault();const p=useProjectStore.getState();if (event.key.toLowerCase()==='v') void pasteEntry(row.dataset.dir==='true'?row.dataset.path!:parent(row.dataset.path!));else fileClipboard={root:p.root,path:row.dataset.path!,cut:event.key.toLowerCase()==='x'};}
    };
    document.addEventListener('contextmenu',open);document.addEventListener('keydown',key);
    return()=>{document.removeEventListener('contextmenu',open);document.removeEventListener('keydown',key);};
  },[]);
  useLayoutEffect(()=>{
    if (!menu) return;
    const r=ref.current?.getBoundingClientRect();
    setPosition({left:Math.max(8,Math.min(menu.x,window.innerWidth-(r?.width??280)-8)),top:Math.max(8,Math.min(menu.y,window.innerHeight-(r?.height??0)-8))});
    previous.current=document.activeElement as HTMLElement;
    ref.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
    return()=>{if (previous.current?.isConnected) previous.current.focus();};
  },[menu]);
  useEffect(()=>{
    if (!menu) return;
    const down=(e:PointerEvent)=>{if(!ref.current?.contains(e.target as Node))closeContextMenu();};
    const close=()=>closeContextMenu();window.addEventListener('pointerdown',down,true);window.addEventListener('resize',close);window.addEventListener('blur',close);
    return()=>{window.removeEventListener('pointerdown',down,true);window.removeEventListener('resize',close);window.removeEventListener('blur',close);};
  },[menu]);
  if(!menu)return null;
  return createPortal(<div ref={ref} className="shark-context-menu" role="menu" aria-label="Quick actions" style={position} onKeyDown={e=>{
    if(e.key==='Escape'||e.key==='Tab'){e.preventDefault();closeContextMenu();return;}
    const items=[...ref.current!.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];const index=items.indexOf(document.activeElement as HTMLButtonElement);
    if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();items[e.key==='Home'?0:e.key==='End'?items.length-1:(index+(e.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();}
    else if(e.key.length===1&&!e.ctrlKey&&!e.metaKey){const next=[...items.slice(index+1),...items.slice(0,index+1)].find(item=>item.textContent?.toLowerCase().startsWith(e.key.toLowerCase()));next?.focus();}
  }}>{menu.items.map((item,i)=>item==='separator'?<hr key={i}/>:<button key={item.label+i} role="menuitem" disabled={item.disabled} className={item.danger?'danger':''} onClick={()=>{closeContextMenu();Promise.resolve(item.run()).catch(e=>useProjectStore.setState({error:String(e)}));}}><span>{item.label}</span>{item.shortcut&&<kbd aria-hidden="true">{item.shortcut}</kbd>}</button>)}</div>,document.body);
}
