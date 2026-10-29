import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowLeft, ArrowRight, BellRing, Bot, Check, CircleAlert, LoaderCircle, Mail, MessageSquarePlus, NotebookPen, Plus, Send, ShieldCheck, Trash2, UserRound, X } from "lucide-react";
import { ClaimBadge } from "../components/ClaimBadge";
import { ErrorState } from "../components/Feedback";
import {
  cancelAction,
  confirmAction,
  createChatConversation,
  getActionAudit,
  deleteChatConversation,
  getAISettings,
  getChatConversation,
  getChatConversations,
  sendChatTurn,
  type ChatMessage,
  type ChatToolEvent,
  type PendingAction,
} from "../lib/api";
import { formatWhen } from "../lib/reminders";

function displayToolName(value: string) {
  return value.replaceAll("_", " ");
}

export function ToolResultCard({ event, onTrace, onClarify }: {
  event: ChatToolEvent;
  onTrace: (claimId: string) => void;
  onClarify: (orderId: string) => void;
}) {
  const data = event.data ?? {};
  const clarification = data.clarification;
  const orders = Array.isArray(data.orders) ? data.orders : [];
  const stageSummaries = Array.isArray(data.stage_summaries) ? data.stage_summaries : [];
  const findings = Array.isArray(data.findings) ? data.findings.slice(0, 3) : [];
  // A brief's own claim already covers its findings, so per-finding claims are not listed separately.
  const findingClaimIds = new Set(findings.map((finding: Record<string, any>) => finding.claim_id).filter(Boolean));
  const summaryClaimIds = event.claim_ids.filter((claimId) => !findingClaimIds.has(claimId));
  const cardClaimIds = summaryClaimIds.length > 0 ? summaryClaimIds : event.claim_ids;

  return (
    <section className="chat-tool-card">
      <div className="chat-tool-header"><span className="tool-state-dot" /><span>{displayToolName(event.tool_name)}</span><small>{event.result_status}</small></div>
      <p>{event.summary}</p>
      {typeof data.match_count === "number" && (
        <div className="chat-tool-metrics"><strong>{data.match_count} orders</strong><span>{Number(data.matched_total_pieces ?? 0).toLocaleString()} pieces matched</span></div>
      )}
      {typeof data.risk_level === "string" && (
        <div className={`chat-tool-highlight risk-${data.risk_level.toLowerCase()}`}><span>{data.order_id}</span><strong>{data.risk_level} RISK</strong></div>
      )}
      {typeof data.status === "string" && typeof data.reason_code === "string" && (
        <div className="chat-tool-highlight"><span>{data.stage} · {data.target_date}</span><strong>{data.status.replaceAll("_", " ")}</strong></div>
      )}
      {stageSummaries.length > 0 && (
        <div className="chat-tool-stage-list">
          {stageSummaries.slice(0, 4).map((stage: Record<string, any>) => (
            <span key={stage.stage}>{stage.stage}<b>{stage.total_pieces?.toLocaleString() ?? "—"}</b></span>
          ))}
        </div>
      )}
      {Array.isArray(clarification?.candidate_order_ids) && (
        <div className="chat-clarification"><strong>{clarification.question ?? "Which order do you mean?"}</strong>
          <div>{clarification.candidate_order_ids.map((id: string) => <button key={id} onClick={() => onClarify(id)}>{id}<ArrowRight size={13} /></button>)}</div>
        </div>
      )}
      {orders.slice(0, 5).map((order: Record<string, any>) => (
        <div className="chat-order-line" key={order.order_id}><code>{order.order_id}</code><span>{order.customer}</span><span>{order.current_stage}</span><b>{Number(order.pieces).toLocaleString()} pcs</b></div>
      ))}
      {findings.map((finding: Record<string, any>) => (
        <div className="chat-finding-line" key={finding.finding_id}><span className={`severity-label ${String(finding.severity).toLowerCase()}`}>{finding.severity}</span><span>{finding.summary}</span></div>
      ))}
      {cardClaimIds.length > 0 && <div className="chat-claim-list">{cardClaimIds.map((claimId) => <ClaimBadge key={claimId} claimId={claimId} onClick={onTrace} />)}</div>}
    </section>
  );
}

const CLAIM_ID = String.raw`CLM-\d{8}-[A-Z]+-\d{3}-[0-9a-f]{8}`;
// A whole line that only cites evidence, e.g. "- Evidence: CLM-..." or "**Claim:** [CLM-...]".
const EVIDENCE_LINE = new RegExp(
  String.raw`^[ \t]*(?:[-*+][ \t]+)?(?:\*\*|__)?(?:evidence|claims?|sources?)?(?:\*\*|__)?[ \t]*:?[ \t]*(?:\*\*|__)?[ \t]*` +
    String.raw`[\[(\x60]?${CLAIM_ID}[\])\x60]?(?:[ \t]*[,;][ \t]*[\[(\x60]?${CLAIM_ID}[\])\x60]?)*[ \t.]*$\n?`,
  "gim",
);
// A claim ID inside a sentence, with any "Evidence:" label and brackets around it.
const INLINE_CLAIM = new RegExp(
  String.raw`[ \t]*[\[(]?(?:(?:evidence|claim)[ \t]*:?[ \t]*)?\x60?${CLAIM_ID}\x60?[\])]?`,
  "gi",
);

// Evidence is shown once at the end of the reply, so claim IDs are removed from the text.
export function stripClaimReferences(content: string) {
  return content
    .replace(EVIDENCE_LINE, "")
    .replace(INLINE_CLAIM, "")
    .replace(/[ \t]+([.,;:])/g, "$1");
}

// Model replies are Markdown. Raw HTML is not rendered.
export function AssistantMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
        table: ({ children }) => <div className="markdown-table-wrap"><table>{children}</table></div>,
      }}
    >
      {stripClaimReferences(content)}
    </ReactMarkdown>
  );
}

const ACTION_COPY = {
  create_reminder: { title: "Reminder", icon: BellRing, done: "Reminder saved. It now appears on the Reminders page." },
  add_order_note: { title: "Order note", icon: NotebookPen, done: "Note recorded in the action log." },
  draft_chase_up_message: { title: "Chase-up draft", icon: Mail, done: "Draft saved to the action log. It was not sent to anyone." },
} as const;

export function PendingActionCard({ action }: { action: PendingAction }) {
  const queryClient = useQueryClient();
  // The action log is the source of truth, so the card shows the right state after a reload.
  const audit = useQuery({ queryKey: ["action-audit"], queryFn: getActionAudit });
  const decide = useMutation({
    mutationFn: (choice: "confirm" | "cancel") => (choice === "confirm" ? confirmAction : cancelAction)(action.confirmation_token),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["action-audit"] });
      queryClient.invalidateQueries({ queryKey: ["reminders"] });
    },
  });
  const recorded = audit.data?.find((item) => item.confirmation_token === action.confirmation_token)?.status;
  const state = decide.data ? (decide.variables === "confirm" ? "CONFIRMED" : "CANCELLED") : recorded ?? "PREPARED";
  const copy = ACTION_COPY[action.preview.action_type];
  const Icon = copy.icon;
  const text = action.preview.payload.message ?? action.preview.payload.note ?? "";

  return (
    <section className={`pending-action-card state-${state.toLowerCase()}`} aria-label={`${copy.title} awaiting confirmation`}>
      <div className="pending-action-head">
        <span className="pending-action-icon"><Icon size={16} /></span>
        <div><strong>{copy.title}</strong><span className="mono">{action.preview.target}</span></div>
        <span className="pending-action-state">{state === "PREPARED" ? "Needs your confirmation" : state === "CONFIRMED" ? "Confirmed" : "Cancelled"}</span>
      </div>
      {action.preview.payload.remind_at && <div className="pending-action-when">{formatWhen(action.preview.payload.remind_at)}</div>}
      <p className="pending-action-text">{text}</p>
      {state === "PREPARED" ? (
        <div className="pending-action-buttons">
          <button className="button button-primary button-small" disabled={decide.isPending} onClick={() => decide.mutate("confirm")}><Check size={14} /> Confirm</button>
          <button className="button button-secondary button-small" disabled={decide.isPending} onClick={() => decide.mutate("cancel")}><X size={14} /> Cancel</button>
          <span className="pending-action-hint">Nothing happens until you confirm.</span>
        </div>
      ) : (
        <p className="pending-action-result">{state === "CONFIRMED" ? copy.done : "Cancelled. Nothing was saved."}</p>
      )}
      {decide.error && <p className="reminder-error">{decide.error.message}</p>}
    </section>
  );
}

function AssistantContent({ message, onTrace, onClarify }: {
  message: ChatMessage;
  onTrace: (claimId: string) => void;
  onClarify: (orderId: string) => void;
}) {
  const events = message.metadata?.tool_events ?? [];
  return (
    <>
      <div className="chat-bubble assistant-bubble"><div className="assistant-copy"><AssistantMarkdown content={message.content} /></div></div>
      {events
        .filter((event) => !(event.tool_name === "prepare_action" && event.result_status === "PREPARED"))
        .map((event, index) => <ToolResultCard key={`${event.tool_name}-${index}`} event={event} onTrace={onTrace} onClarify={onClarify} />)}
      {(message.metadata?.pending_actions ?? []).map((action) => <PendingActionCard key={action.confirmation_token} action={action} />)}
    </>
  );
}

export function ChatPage({ onTrace }: { onTrace: (claimId: string) => void }) {
  const { conversationId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const initialMessage = (location.state as { initialMessage?: string } | null)?.initialMessage;
  const [activeId, setActiveId] = useState<string | null>(conversationId ?? null);
  const [draft, setDraft] = useState("");
  const [optimisticMessages, setOptimisticMessages] = useState<ChatMessage[]>([]);
  const [sendError, setSendError] = useState("");
  const [sending, setSending] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const messageEndRef = useRef<HTMLDivElement>(null);
  const autoSentRef = useRef(false);
  const conversations = useQuery({ queryKey: ["chat-conversations"], queryFn: getChatConversations });
  const conversation = useQuery({
    queryKey: ["chat-conversation", activeId],
    queryFn: () => getChatConversation(activeId!),
    enabled: Boolean(activeId),
  });
  const aiSettings = useQuery({ queryKey: ["ai-settings"], queryFn: getAISettings });
  const removeConversation = useMutation({
    mutationFn: deleteChatConversation,
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
      queryClient.removeQueries({ queryKey: ["chat-conversation", deletedId] });
      if (activeId === deletedId) {
        setActiveId(null);
        setOptimisticMessages([]);
        navigate("/chat", { replace: true });
      }
    },
  });

  useEffect(() => {
    setActiveId(conversationId ?? null);
    setOptimisticMessages([]);
  }, [conversationId]);

  const serverMessages = conversation.data?.messages ?? [];
  const messages = [...serverMessages, ...optimisticMessages];

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, sending]);

  async function sendMessage(rawMessage: string) {
    const content = rawMessage.trim();
    if (!content || sending) return;
    setSending(true);
    setSendError("");
    setDraft("");
    const localUserMessage: ChatMessage = {
      role: "user",
      content,
      metadata: {},
      created_at: new Date().toISOString(),
    };
    setOptimisticMessages((current) => [...current, localUserMessage]);
    let requestConversationId = activeId;

    try {
      if (!requestConversationId) {
        const created = await createChatConversation(content.slice(0, 80));
        requestConversationId = created.conversation_id;
        setActiveId(requestConversationId);
        navigate(`/chat/${requestConversationId}`, { replace: true, state: null });
        queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
      }
      const response = await sendChatTurn(requestConversationId, content);
      setOptimisticMessages((current) => [...current, {
        role: "assistant",
        content: response.assistant_message,
        metadata: { tool_events: response.tool_events, pending_actions: response.pending_actions ?? [] },
        created_at: new Date().toISOString(),
      }]);
      await queryClient.invalidateQueries({ queryKey: ["chat-conversation", requestConversationId] });
      queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
      setOptimisticMessages([]);
    } catch (error) {
      setSendError(error instanceof Error ? error.message : "The message could not be sent.");
      if (requestConversationId) {
        const savedConversation = await getChatConversation(requestConversationId).catch(() => null);
        if (savedConversation) {
          queryClient.setQueryData(["chat-conversation", requestConversationId], savedConversation);
          setOptimisticMessages([]);
        }
        queryClient.invalidateQueries({ queryKey: ["chat-conversation", requestConversationId] });
        queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
      }
    } finally {
      setSending(false);
    }
  }

  useEffect(() => {
    if (!initialMessage || autoSentRef.current) return;
    autoSentRef.current = true;
    navigate(location.pathname, { replace: true, state: null });
    void sendMessage(initialMessage);
  }, [initialMessage]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage(draft);
  }

  function startNewChat() {
    setActiveId(null);
    setOptimisticMessages([]);
    setDraft("");
    setSendError("");
    autoSentRef.current = false;
    navigate("/chat");
  }

  return (
    <div className="chat-workspace">
      <aside className={`chat-history ${showHistory ? "chat-history-open" : ""}`}>
        <div className="chat-history-top">
          <Link to="/" className="chat-back-link"><ArrowLeft size={16} /> Workspace</Link>
          <button className="button button-secondary chat-new-button" onClick={startNewChat}><Plus size={15} /> New chat</button>
        </div>
        <div className="chat-history-label">RECENT CONVERSATIONS</div>
        <div className="chat-history-list">
          {conversations.data?.map((item) => (
            <div className={`chat-history-item ${item.conversation_id === activeId ? "active" : ""}`} key={item.conversation_id}>
              <button onClick={() => { setShowHistory(false); navigate(`/chat/${item.conversation_id}`); }}>{item.title || "New conversation"}<small>{item.message_count} messages</small></button>
              <button className="chat-delete-button" aria-label={`Delete ${item.title}`} title="Delete conversation" onClick={() => removeConversation.mutate(item.conversation_id)}><Trash2 size={14} /></button>
            </div>
          ))}
          {conversations.data?.length === 0 && <p className="chat-history-empty">Your conversations will appear here.</p>}
        </div>
        <div className="chat-history-foot"><ShieldCheck size={15} /><span>Track 1 dataset<br /><small>Only you can see your conversations.</small></span></div>
      </aside>

      <main className="chat-main">
        <header className="chat-topbar">
          <button className="icon-button chat-history-toggle" onClick={() => setShowHistory(!showHistory)} aria-label="Toggle conversation history"><MessageSquarePlus size={18} /></button>
          <div className="chat-agent-mark"><Bot size={17} /></div>
          <div className="chat-agent-heading"><strong>Operations assistant</strong><span><i /> {aiSettings.data?.has_api_key ? "Provider configured" : "AI not configured"}</span></div>
          <Link to="/settings" className="chat-settings-link">AI settings</Link>
          <Link to="/" className="chat-exit-link">Exit <X size={15} /></Link>
        </header>

        <div className="chat-scroll-area">
          {messages.length === 0 && !sending && (
            <section className="chat-welcome">
              <div className="chat-welcome-icon"><Bot size={24} /></div>
              <span className="eyebrow">FIELDWORK AI PREVIEW</span>
              <h1>What should we<br /><em>look into?</em></h1>
              <p>Ask about current orders, factory output, delivery risk or a proposed order. Answers use configured tools and carry evidence links.</p>
              {!aiSettings.data?.has_api_key && <div className="chat-setup-callout"><CircleAlert size={16} /><span>Configure a provider API key in <Link to="/settings">AI settings</Link> before sending a question.</span></div>}
            </section>
          )}
          {messages.map((message, index) => (
            <article className={`chat-message ${message.role === "user" ? "user-message" : "assistant-message"}`} key={`${message.created_at}-${index}`}>
              <div className={`chat-message-avatar ${message.role}`} aria-hidden="true">{message.role === "user" ? <UserRound size={15} /> : <Bot size={16} />}</div>
              <div className="chat-message-content">
                <div className="chat-message-meta"><strong>{message.role === "user" ? "You" : "Operations assistant"}</strong><time>{new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time></div>
                {message.role === "user" ? <div className="chat-bubble user-bubble">{message.content}</div> : <AssistantContent message={message} onTrace={onTrace} onClarify={(id) => void sendMessage(`Tell me about order ${id}.`)} />}
              </div>
            </article>
          ))}
          {sending && <div className="chat-thinking"><LoaderCircle size={16} className="spin" /><span>Checking approved tools…</span></div>}
          {sendError && <div className="chat-inline-error"><ErrorState message={sendError} /></div>}
          {conversation.isLoading && <div className="chat-thinking"><LoaderCircle size={16} className="spin" /><span>Loading conversation…</span></div>}
          <div ref={messageEndRef} />
        </div>

        <footer className="chat-composer-wrap">
          <form className="chat-composer" onSubmit={submit}>
            <textarea
              aria-label="Message the operations assistant"
              value={draft}
              maxLength={2000}
              rows={1}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage(draft);
                }
              }}
              placeholder="Ask a follow-up question…"
            />
            <button type="submit" className="chat-send-button" disabled={!draft.trim() || sending} aria-label="Send message"><Send size={17} /></button>
          </form>
          <div className="chat-composer-foot"><span>Enter to send · Shift+Enter for a new line</span><span>Decision support only · check claim evidence</span></div>
        </footer>
      </main>
    </div>
  );
}