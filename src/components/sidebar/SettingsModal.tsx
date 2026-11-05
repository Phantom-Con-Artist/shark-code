import React, { useState } from 'react';
import { Key, ShieldCheck, Check, Save } from 'lucide-react';
import { useAgentStore } from '@/stores/useAgentStore';
import { AIProvider } from '@/types';

export const SettingsModal: React.FC = () => {
  const { apiKeys, setApiKey } = useAgentStore();
  const [keys, setKeys] = useState(apiKeys);
  const [savedSuccess, setSavedSuccess] = useState(false);

  const providers: { id: AIProvider; name: string; placeholder: string; docUrl: string }[] = [
    {
      id: 'anthropic',
      name: 'Anthropic Claude',
      placeholder: 'sk-ant-api03-...',
      docUrl: 'https://console.anthropic.com',
    },
    {
      id: 'gemini',
      name: 'Google Gemini',
      placeholder: 'AIzaSy...',
      docUrl: 'https://aistudio.google.com',
    },
    {
      id: 'openai',
      name: 'OpenAI (GPT-4o / o3-mini)',
      placeholder: 'sk-proj-...',
      docUrl: 'https://platform.openai.com',
    },
    {
      id: 'ollama',
      name: 'Ollama / Local LLM Endpoint',
      placeholder: 'http://localhost:11434',
      docUrl: 'https://ollama.ai',
    },
  ];

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    Object.entries(keys).forEach(([p, k]) => {
      setApiKey(p as AIProvider, k);
    });
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 2000);
  };

  return (
    <div className="flex flex-col h-full bg-[#18181b] border-r border-[#27272a] select-none p-4 overflow-y-auto">
      <div className="flex items-center space-x-2 pb-3 mb-4 border-b border-[#27272a]">
        <Key size={18} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-zinc-100">BYOK Settings</h2>
      </div>

      <div className="text-xs text-zinc-400 mb-4 leading-relaxed">
        Shark Code communicates directly with LLM providers from your machine. 
        Your keys are never proxied through external servers and are stored in your operating system&apos;s encrypted keyring.
      </div>

      <form onSubmit={handleSave} className="space-y-4 flex-1">
        {providers.map((p) => (
          <div key={p.id} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <label className="font-medium text-zinc-200">{p.name}</label>
              <a
                href={p.docUrl}
                target="_blank"
                rel="noreferrer"
                className="text-blue-400 hover:underline text-[11px]"
              >
                Get Key
              </a>
            </div>
            <input
              type={p.id === 'ollama' ? 'text' : 'password'}
              placeholder={p.placeholder}
              value={keys[p.id] || ''}
              onChange={(e) => setKeys({ ...keys, [p.id]: e.target.value })}
              className="w-full bg-[#27272a] border border-[#3f3f46] rounded px-2.5 py-1.5 text-xs text-zinc-100 placeholder-zinc-500 outline-none focus:border-blue-500 font-mono"
            />
          </div>
        ))}

        <div className="pt-2">
          <button
            type="submit"
            className="w-full flex items-center justify-center space-x-2 bg-blue-600 hover:bg-blue-500 text-white rounded py-2 text-xs font-medium transition-colors shadow"
          >
            {savedSuccess ? (
              <>
                <Check size={14} className="text-white" />
                <span>Saved Securely!</span>
              </>
            ) : (
              <>
                <Save size={14} />
                <span>Save API Keys</span>
              </>
            )}
          </button>
        </div>
      </form>

      <div className="mt-auto pt-4 border-t border-[#27272a] flex items-center space-x-2 text-[11px] text-emerald-400">
        <ShieldCheck size={15} />
        <span>Hardware-backed OS Keychain active</span>
      </div>
    </div>
  );
};
