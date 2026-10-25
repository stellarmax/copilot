import { useState } from "react";
import { ArrowRight, Bot, Search, Sparkles } from "lucide-react";

interface ChatEntryProps {
  onAsk: (message: string) => void;
}

const examples = [
  "Which orders need attention?",
  "How did assembly perform last week?",
  "Can we take 500 hoodies by April 30?",
];

export function ChatEntry({ onAsk }: ChatEntryProps) {
  const [message, setMessage] = useState("");

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = message.trim();
    if (!value) return;
    onAsk(value);
    setMessage("");
  }

  return (
    <section className="chat-entry" aria-labelledby="chat-entry-title">
      <div className="chat-entry-heading">
        <span className="chat-entry-icon"><Bot size={18} /></span>
        <div>
          <span className="eyebrow">OPERATIONS ASSISTANT</span>
          <h2 id="chat-entry-title">Ask operations</h2>
        </div>
        <span className="chat-entry-demo"><Sparkles size={12} /> AI PREVIEW</span>
      </div>
      <form className="chat-entry-form" onSubmit={submit}>
        <Search size={19} aria-hidden="true" />
        <input
          aria-label="Ask an operations question"
          value={message}
          maxLength={2000}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Ask about orders, output, delivery risk…"
        />
        <button className="chat-entry-submit" type="submit" disabled={!message.trim()} aria-label="Open chat and send question">
          <ArrowRight size={18} />
        </button>
      </form>
      <div className="chat-entry-examples">
        <span>TRY</span>
        {examples.map((example) => (
          <button key={example} type="button" onClick={() => onAsk(example)}>{example}</button>
        ))}
      </div>
      <p className="chat-entry-note">AI answers use the configured provider. Verify business claims with their attached evidence.</p>
    </section>
  );
}