import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlarmClock, BellPlus, BellRing, CalendarPlus, Check, Lightbulb, Pencil, Repeat, X } from "lucide-react";
import { ClaimBadge } from "../components/ClaimBadge";
import { ErrorState, LoadingState } from "../components/Feedback";
import { notificationsSupported } from "../components/ReminderNotifier";
import {
  REMINDERS_ICS_URL,
  createReminder,
  dismissReminderSuggestion,
  getReminderSuggestions,
  getReminders,
  restoreReminderSuggestions,
  updateReminder,
  type Reminder,
  type ReminderRepeat,
  type ReminderSuggestion,
} from "../lib/api";
import {
  DUE_LABELS,
  REPEAT_LABELS,
  SNOOZE_OPTIONS,
  defaultReminderTime,
  describeDaysToDue,
  formatWhen,
  fromLocalInput,
  toLocalInput,
  tomorrowMorning,
} from "../lib/reminders";

function useReminderMutation<T>(mutationFn: (value: T) => Promise<unknown>, onDone?: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      onDone?.();
      queryClient.invalidateQueries({ queryKey: ["reminders"] });
      queryClient.invalidateQueries({ queryKey: ["reminder-suggestions"] });
      queryClient.invalidateQueries({ queryKey: ["action-audit"] });
    },
  });
}

function RepeatSelect({ value, onChange, label = "Repeat" }: { value: ReminderRepeat; onChange: (value: ReminderRepeat) => void; label?: string }) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value as ReminderRepeat)} aria-label={label}>
      {(Object.keys(REPEAT_LABELS) as ReminderRepeat[]).map((key) => <option key={key} value={key}>{REPEAT_LABELS[key]}</option>)}
    </select>
  );
}

function SnoozeMenu({ reminder }: { reminder: Reminder }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const snooze = useReminderMutation((until: Date) => updateReminder(reminder.reminder_id, { remind_at: until.toISOString() }), () => setOpen(false));

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  return (
    <div className="snooze-wrap" ref={wrap}>
      <button className="icon-button" title="Snooze" aria-label={`Snooze reminder for ${reminder.order_id}`} aria-haspopup="menu"
        aria-expanded={open} onClick={() => setOpen(!open)}><AlarmClock size={15} /></button>
      {open && (
        <div className="snooze-menu" role="menu" aria-label="Snooze until">
          <span>Snooze until</span>
          {SNOOZE_OPTIONS.map((option) => (
            <button key={option.label} type="button" role="menuitem" disabled={snooze.isPending}
              onClick={() => snooze.mutate(option.until(new Date()))}>{option.label}</button>
          ))}
          {snooze.error && <p className="reminder-error">{snooze.error.message}</p>}
        </div>
      )}
    </div>
  );
}

function OrderContext({ reminder }: { reminder: Reminder }) {
  const context = reminder.order_context;
  if (!context) return <small className="reminder-order-meta">Order not found in the data</small>;
  return (
    <small className="reminder-order-meta">
      {context.status === "COMPLETE" ? "Complete" : context.current_stage}
      {context.risk_level && context.status !== "COMPLETE" && (
        <span className={`risk-chip risk-${context.risk_level.toLowerCase()}`}>{context.risk_level}</span>
      )}
      {context.status !== "COMPLETE" && <span>{describeDaysToDue(context.days_to_due)}</span>}
    </small>
  );
}

function ReminderRow({ reminder, onTrace }: { reminder: Reminder; onTrace: (claimId: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [orderId, setOrderId] = useState(reminder.order_id);
  const [note, setNote] = useState(reminder.note);
  const [when, setWhen] = useState(toLocalInput(reminder.remind_at));
  const [repeat, setRepeat] = useState<ReminderRepeat>(reminder.repeat ?? "NONE");
  const update = useReminderMutation((changes: Parameters<typeof updateReminder>[1]) => updateReminder(reminder.reminder_id, changes),
    () => setEditing(false));
  const active = reminder.status === "ACTIVE";
  const repeating = reminder.repeat && reminder.repeat !== "NONE";

  if (editing) {
    return (
      <tr className="reminder-editing">
        <td>
          <input type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} aria-label="Reminder time" />
          <RepeatSelect value={repeat} onChange={setRepeat} />
        </td>
        <td><input value={orderId} onChange={(event) => setOrderId(event.target.value)} aria-label="Order ID" /></td>
        <td>
          <input value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} aria-label="Reminder note" />
          {update.error && <p className="reminder-error">{update.error.message}</p>}
        </td>
        <td />
        <td className="reminder-actions">
          <button className="button button-primary button-small" disabled={update.isPending || !note.trim() || !when}
            onClick={() => update.mutate({ order_id: orderId.trim(), note: note.trim(), remind_at: fromLocalInput(when), repeat })}>Save</button>
          <button className="button button-secondary button-small" onClick={() => setEditing(false)}>Discard</button>
        </td>
      </tr>
    );
  }
  return (
    <tr className={active ? "" : "reminder-closed"}>
      <td>
        <span className="mono">{formatWhen(reminder.remind_at)}</span>
        {repeating && <small className="reminder-repeat"><Repeat size={12} /> {REPEAT_LABELS[reminder.repeat]}</small>}
      </td>
      <td><span className="mono">{reminder.order_id}</span><OrderContext reminder={reminder} /></td>
      <td>
        {reminder.note}
        {reminder.source === "assistant" && <span className="reminder-source">via AI chat</span>}
        {reminder.claim_id && <span className="reminder-claim"><ClaimBadge claimId={reminder.claim_id} onClick={onTrace} /></span>}
        {active && reminder.order_context?.suggest_close && (
          <p className="reminder-hint">This order is already complete.{" "}
            <button className="text-button" onClick={() => update.mutate({ status: repeating ? "CANCELLED" : "DONE" })}>
              {repeating ? "Stop this reminder" : "Mark done"}
            </button>
          </p>
        )}
      </td>
      <td><span className={`due-chip due-${reminder.due_state.toLowerCase()}`}>{DUE_LABELS[reminder.due_state]}</span></td>
      <td className="reminder-actions">
        {active && (
          <>
            <SnoozeMenu reminder={reminder} />
            <button className="icon-button" title="Edit" aria-label={`Edit reminder for ${reminder.order_id}`} onClick={() => setEditing(true)}><Pencil size={15} /></button>
            <button className="icon-button" title={repeating ? "Done for this time" : "Mark done"} aria-label={`Mark reminder for ${reminder.order_id} done`} onClick={() => update.mutate({ status: "DONE" })}><Check size={15} /></button>
            <button className="icon-button" title="Cancel reminder" aria-label={`Cancel reminder for ${reminder.order_id}`} onClick={() => update.mutate({ status: "CANCELLED" })}><X size={15} /></button>
          </>
        )}
        {update.error && !editing && <p className="reminder-error">{update.error.message}</p>}
      </td>
    </tr>
  );
}

function SuggestionRow({ suggestion, onTrace }: { suggestion: ReminderSuggestion; onTrace: (claimId: string) => void }) {
  const add = useReminderMutation(() => createReminder({
    order_id: suggestion.order_id,
    note: suggestion.suggested_note,
    remind_at: tomorrowMorning().toISOString(),
    claim_id: suggestion.claim_id,
  }));
  const dismiss = useReminderMutation(() => dismissReminderSuggestion(suggestion.order_id));
  const error = add.error ?? dismiss.error;
  return (
    <li className="suggestion-row">
      <span className={`risk-chip risk-${suggestion.risk_level.toLowerCase()}`}>{suggestion.risk_level}</span>
      <div className="suggestion-copy">
        <strong><span className="mono">{suggestion.order_id}</span> · {suggestion.customer}</strong>
        <span>{suggestion.product} · {suggestion.pieces.toLocaleString()} pcs · {suggestion.current_stage}</span>
        <span className="suggestion-reasons">{suggestion.reasons.join(" · ")}</span>
        {error && <p className="reminder-error">{error.message}</p>}
      </div>
      {suggestion.claim_id && <ClaimBadge claimId={suggestion.claim_id} onClick={onTrace} />}
      <div className="suggestion-actions">
        <button className="button button-primary button-small" disabled={add.isPending} onClick={() => add.mutate(undefined)}>
          <BellPlus size={14} /> Remind me tomorrow 9:00
        </button>
        <button className="button button-secondary button-small" disabled={dismiss.isPending} onClick={() => dismiss.mutate(undefined)}>Dismiss</button>
      </div>
    </li>
  );
}

function SuggestionsPanel({ onTrace }: { onTrace: (claimId: string) => void }) {
  const suggestions = useQuery({ queryKey: ["reminder-suggestions"], queryFn: getReminderSuggestions });
  const restore = useReminderMutation(() => restoreReminderSuggestions());
  const data = suggestions.data;
  return (
    <section className="panel suggestion-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">SUGGESTED FOLLOW-UPS</span>
          <h2><Lightbulb size={17} /> {data ? data.total_suggestions : "—"} <small>high-risk orders without a reminder</small></h2>
        </div>
        {data && data.dismissed_count > 0 && (
          <button className="text-button" disabled={restore.isPending} onClick={() => restore.mutate(undefined)}>Show {data.dismissed_count} dismissed</button>
        )}
      </div>
      {suggestions.isLoading && <LoadingState label="Checking order risk" />}
      {suggestions.error && <ErrorState message={suggestions.error.message} />}
      {data && data.suggestions.length === 0 && <div className="empty-row">Every high-risk order already has a reminder.</div>}
      {data && data.suggestions.length > 0 && (
        <ul className="suggestion-list">{data.suggestions.map((item) => <SuggestionRow key={item.order_id} suggestion={item} onTrace={onTrace} />)}</ul>
      )}
      {data && (
        <p className="panel-bottom-note">
          Picked by the order risk rules as of the business date {data.business_as_of_date}
          {data.total_suggestions > data.suggestions.length ? ` (showing the ${data.suggestions.length} most urgent)` : ""}. {data.rule_notice}
        </p>
      )}
    </section>
  );
}

function NotificationSetting() {
  const [permission, setPermission] = useState(() => (notificationsSupported() ? Notification.permission : "unsupported"));
  if (permission === "granted") {
    return <span className="notify-state on"><BellRing size={14} /> Desktop notifications on</span>;
  }
  if (permission === "unsupported") {
    return <span className="notify-state">This browser does not support desktop notifications</span>;
  }
  if (permission === "denied") {
    return <span className="notify-state">Notifications are blocked in your browser's site settings</span>;
  }
  return (
    <button className="button button-secondary button-small" onClick={async () => setPermission(await Notification.requestPermission())}>
      <BellRing size={14} /> Turn on desktop notifications
    </button>
  );
}

export function RemindersPage({ onTrace }: { onTrace: (claimId: string) => void }) {
  const [showClosed, setShowClosed] = useState(false);
  const [orderId, setOrderId] = useState("");
  const [note, setNote] = useState("");
  const [when, setWhen] = useState(defaultReminderTime());
  const [repeat, setRepeat] = useState<ReminderRepeat>("NONE");
  const reminders = useQuery({
    queryKey: ["reminders", showClosed],
    queryFn: () => getReminders(showClosed),
    refetchInterval: 60_000,
  });
  const create = useReminderMutation(createReminder, () => {
    setOrderId("");
    setNote("");
    setWhen(defaultReminderTime());
    setRepeat("NONE");
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    create.mutate({ order_id: orderId.trim(), note: note.trim(), remind_at: fromLocalInput(when), repeat });
  }

  return (
    <div className="page-stack">
      <section className="page-intro">
        <div>
          <span className="eyebrow">FOLLOW-UPS</span>
          <p>Reminders for orders, on your computer's clock. While this app is open you get a desktop notification when one comes due; nothing is e-mailed.</p>
        </div>
        <NotificationSetting />
      </section>
      <SuggestionsPanel onTrace={onTrace} />
      <section className="panel filter-panel">
        <div className="filter-title"><BellPlus size={16} /><strong>New reminder</strong><span>Order must exist</span></div>
        <form className="filter-form reminder-form" onSubmit={submit}>
          <label>Order ID<input value={orderId} onChange={(event) => setOrderId(event.target.value)} placeholder="ORD-029" required /></label>
          <label>Note<input value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="What should you check?" required /></label>
          <label>When<input type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} required /></label>
          <label>Repeat<RepeatSelect value={repeat} onChange={setRepeat} label="Repeat new reminder" /></label>
          <button className="button button-primary" type="submit" disabled={create.isPending}><BellPlus size={16} /> Add reminder</button>
        </form>
        {create.error && <ErrorState message={create.error.message} />}
      </section>
      <section className="panel table-panel">
        <div className="panel-heading table-heading">
          <div><span className="eyebrow">{showClosed ? "ALL REMINDERS" : "ACTIVE REMINDERS"}</span><h2>{reminders.data?.length ?? "—"} <small>reminders</small></h2></div>
          <div className="reminder-table-tools">
            <a className="button button-secondary button-small" href={REMINDERS_ICS_URL} download><CalendarPlus size={14} /> Export to calendar</a>
            <label className="reminder-toggle"><input type="checkbox" checked={showClosed} onChange={(event) => setShowClosed(event.target.checked)} /> Show done and cancelled</label>
          </div>
        </div>
        {reminders.isLoading && <LoadingState label="Loading reminders" />}
        {reminders.error && <ErrorState message={reminders.error.message} />}
        {reminders.data && reminders.data.length === 0 && <div className="empty-row">No reminders yet. Add one above, pick a suggestion, or ask the AI assistant to prepare one.</div>}
        {reminders.data && reminders.data.length > 0 && (
          <div className="table-scroll">
            <table className="data-table reminder-table">
              <thead><tr><th>WHEN</th><th>ORDER</th><th>NOTE</th><th>STATUS</th><th /></tr></thead>
              <tbody>{reminders.data.map((reminder) => <ReminderRow key={reminder.reminder_id} reminder={reminder} onTrace={onTrace} />)}</tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
