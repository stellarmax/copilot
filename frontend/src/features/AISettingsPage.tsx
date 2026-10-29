import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Eye, EyeOff, KeyRound, LockKeyhole, Plus, RefreshCw, ShieldCheck, Trash2, X } from "lucide-react";
import { ErrorState, LoadingState } from "../components/Feedback";
import {
  clearChatMemories,
  createChatMemory,
  deleteAICredential,
  deleteChatMemory,
  getAIProviderCatalog,
  getAISettings,
  getChatMemories,
  getChatMemoryPreference,
  saveAISettings,
  setChatMemoryPreference,
  testAIConnection,
} from "../lib/api";
import type { AIProviderId } from "../lib/api";

export function AISettingsPage() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["ai-settings"], queryFn: getAISettings });
  const catalog = useQuery({ queryKey: ["ai-provider-catalog"], queryFn: getAIProviderCatalog, staleTime: Infinity });
  const memoryPreference = useQuery({ queryKey: ["chat-memory-preference"], queryFn: getChatMemoryPreference });
  const memories = useQuery({
    queryKey: ["chat-memories"],
    queryFn: getChatMemories,
    enabled: memoryPreference.data?.enabled === true,
  });
  const [provider, setProvider] = useState<AIProviderId>("chatgpt");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!settings.data) return;
    setProvider(settings.data.provider);
    setModel(settings.data.model);
  }, [settings.data]);

  const providerModels = catalog.data?.providers.find((item) => item.id === provider)?.models ?? [];
  // A saved key only works with the provider it was issued by.
  const needsNewKey = Boolean(settings.data?.has_api_key && settings.data.provider !== provider && !apiKey.trim());

  function changeProvider(next: AIProviderId) {
    setProvider(next);
    // A model id is only valid for its own provider; default to the new provider's first model.
    setModel(catalog.data?.providers.find((item) => item.id === next)?.models[0]?.id ?? "");
  }

  const save = useMutation({
    mutationFn: () => saveAISettings({
      provider,
      model,
      ...(apiKey.trim() ? { api_key: apiKey } : {}),
    }),
    onSuccess: (data) => {
      queryClient.setQueryData(["ai-settings"], data);
      setApiKey("");
      setNotice("AI settings saved. Your API key is stored encrypted and only your account can use it.");
    },
  });

  const testConnection = useMutation({
    mutationFn: testAIConnection,
    onSuccess: (result) => setNotice(result.message),
    onError: (error) => setNotice(error instanceof Error ? error.message : "Connection test failed."),
  });

  const deleteCredential = useMutation({
    mutationFn: deleteAICredential,
    onSuccess: (data) => {
      queryClient.setQueryData(["ai-settings"], data);
      setNotice("Saved API key removed.");
    },
  });

  const updateMemory = useMutation({
    mutationFn: setChatMemoryPreference,
    onSuccess: (data) => {
      queryClient.setQueryData(["chat-memory-preference"], data);
      if (data.enabled) queryClient.invalidateQueries({ queryKey: ["chat-memories"] });
      setNotice(data.enabled ? "Optional memory enabled." : "Optional memory disabled. Existing memories remain available to review or delete.");
    },
  });

  const addMemory = useMutation({
    mutationFn: createChatMemory,
    onSuccess: () => {
      setMemoryDraft("");
      queryClient.invalidateQueries({ queryKey: ["chat-memories"] });
    },
  });

  const removeMemory = useMutation({
    mutationFn: deleteChatMemory,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["chat-memories"] }),
  });

  const removeAllMemories = useMutation({
    mutationFn: clearChatMemories,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["chat-memories"] }),
  });

  function submitSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    save.mutate();
  }

  function submitMemory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (memoryDraft.trim()) addMemory.mutate(memoryDraft.trim());
  }

  return (
    <div className="page-stack ai-settings-page">
      <section className="page-intro">
        <div><span className="eyebrow">YOUR AGENT CONFIGURATION</span><p>Connect your own AI provider key and decide whether the assistant may keep optional chat memory for you.</p></div>
        <span className="local-only-tag"><ShieldCheck size={15} /> PRIVATE TO YOUR ACCOUNT</span>
      </section>

      <section className="panel ai-settings-panel">
        <div className="panel-heading">
          <div><span className="eyebrow">MODEL PROVIDER</span><h2>AI connection</h2></div>
          <span className={`settings-status ${settings.data?.has_api_key ? "configured" : "not-configured"}`}>
            <span />{settings.data?.has_api_key ? "CONFIGURED" : "NOT CONFIGURED"}
          </span>
        </div>
        {(settings.isLoading || catalog.isLoading) && <LoadingState label="Loading AI settings" />}
        {settings.error && <ErrorState message={settings.error.message} />}
        {catalog.error && <ErrorState message={catalog.error.message} />}
        {settings.data && catalog.data && (
          <form className="ai-settings-form" onSubmit={submitSettings}>
            <div className="provider-selection">
              <div className="provider-icon"><KeyRound size={17} /></div>
              <div><strong>{catalog.data.providers.find((item) => item.id === provider)?.label ?? "AI provider"}</strong><small>The provider endpoint is fixed by the backend</small></div>
              <span className="provider-version">V1</span>
            </div>
            <label>AI provider
              <select required value={provider} onChange={(event) => changeProvider(event.target.value as AIProviderId)}>
                {catalog.data.providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
            <label>Model
              <select required value={model} onChange={(event) => setModel(event.target.value)}>
                {!providerModels.some((item) => item.id === model) && <option value="" disabled>Choose a model</option>}
                {providerModels.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
            <label>API key
              <span className="secret-input-wrap">
                <input
                  type={showKey ? "text" : "password"}
                  autoComplete="new-password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={needsNewKey ? "Enter the API key for this provider" : settings.data.has_api_key ? "Saved key · enter a new key to replace" : "Paste the provider API key"}
                />
                <button type="button" className="secret-toggle" onClick={() => setShowKey(!showKey)} aria-label={showKey ? "Hide API key" : "Show API key"}>
                  {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </span>
            </label>
            <div className="credential-state">
              <LockKeyhole size={15} />
              <span>{needsNewKey ? "You changed provider: enter that provider's API key before saving." : settings.data.has_api_key ? "The saved key is never returned to this page." : "The key is encrypted by the backend before it is stored."}</span>
              {settings.data.updated_at && <time>{new Date(settings.data.updated_at).toLocaleString()}</time>}
            </div>
            {!settings.data.encryption_ready && (
              <div className="settings-warning">Backend encryption is not configured. Set `AI_CREDENTIALS_ENCRYPTION_KEY` on the server and restart it before saving a key.</div>
            )}
            <div className="settings-actions">
              <button className="button button-primary" type="submit" disabled={save.isPending || needsNewKey || (!settings.data.encryption_ready && Boolean(apiKey.trim()))}>
                <LockKeyhole size={15} /> {save.isPending ? "Saving securely" : "Save settings"}
              </button>
              <button className="button button-secondary" type="button" disabled={!settings.data.has_api_key || testConnection.isPending} onClick={() => testConnection.mutate()}>
                <RefreshCw size={15} className={testConnection.isPending ? "spin" : ""} /> {testConnection.isPending ? "Testing" : "Test connection"}
              </button>
              {settings.data.has_api_key && (
                <button className="button button-danger" type="button" disabled={deleteCredential.isPending} onClick={() => deleteCredential.mutate()}>
                  <Trash2 size={15} /> Remove key
                </button>
              )}
            </div>
            {(save.error || testConnection.error || deleteCredential.error) && <ErrorState message={(save.error ?? testConnection.error ?? deleteCredential.error)?.message ?? "Settings request failed."} />}
            {notice && <div className="settings-notice" role="status"><Check size={15} />{notice}</div>}
            <p className="settings-footnote">Connection tests contact your configured provider and may incur provider charges. The API key is sent only to this backend; never paste keys into chat.</p>
          </form>
        )}
      </section>

      <section className="panel memory-settings-panel">
        <div className="panel-heading">
          <div><span className="eyebrow">OPTIONAL · OFF BY DEFAULT</span><h2>Chat memory</h2></div>
          <label className="memory-toggle" aria-label="Enable optional chat memory">
            <input
              type="checkbox"
              checked={memoryPreference.data?.enabled ?? false}
              disabled={!memoryPreference.data || updateMemory.isPending}
              onChange={(event) => updateMemory.mutate(event.target.checked)}
            />
            <span>{memoryPreference.data?.enabled ? "ON" : "OFF"}</span>
          </label>
        </div>
        <p className="memory-description">When enabled, saved preferences may be included as context in future chats. They are not business evidence and never replace live order or production queries.</p>
        {memoryPreference.error && <ErrorState message={memoryPreference.error.message} />}
        {memoryPreference.data?.enabled && (
          <div className="memory-content">
            <form className="memory-add-form" onSubmit={submitMemory}>
              <input value={memoryDraft} maxLength={500} onChange={(event) => setMemoryDraft(event.target.value)} placeholder="Add a preference, e.g. prefer concise summaries" />
              <button className="button button-secondary" type="submit" disabled={!memoryDraft.trim() || addMemory.isPending}><Plus size={15} /> Save memory</button>
            </form>
            {addMemory.error && <ErrorState message={addMemory.error.message} />}
            {memories.isLoading && <LoadingState label="Loading saved memories" />}
            {memories.data?.length === 0 && <div className="empty-row">No saved memories.</div>}
            {memories.data && memories.data.length > 0 && (
              <div className="memory-list">
                {memories.data.map((memory) => (
                  <div className="memory-item" key={memory.memory_id}>
                    <span>{memory.content}</span>
                    <time>{new Date(memory.created_at).toLocaleDateString()}</time>
                    <button className="icon-button" aria-label="Delete saved memory" title="Delete memory" onClick={() => removeMemory.mutate(memory.memory_id)}><X size={15} /></button>
                  </div>
                ))}
                <button className="text-button memory-clear" onClick={() => removeAllMemories.mutate()} disabled={removeAllMemories.isPending}>Clear all memories</button>
              </div>
            )}
          </div>
        )}
        <div className="notice-strip"><span>!</span><p>Each signed-in account has its own key and memories. Nobody else, including the person hosting this app, can use your key through the app.</p></div>
      </section>
    </div>
  );
}