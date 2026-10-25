import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellPlus, Check, Pencil, X } from "lucide-react";
import { ErrorState, LoadingState } from "../components/Feedback";
import { createReminder, getReminders, updateReminder, type Reminder } from "../lib/api";
import { DUE_LABELS, defaultReminderTime, formatWhen, fromLocalInput, toLocalInput } from "../lib/reminders";

function ReminderRow({ reminder }: { reminder: Reminder }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [orderId, setOrderId] = useState(reminder.order_id);
  const [note, setNote] = useState(reminder.note);
  const [when, setWhen] = useState(toLocalInput(reminder.remind_at));
  const update = useMutation({
    mutationFn: (changes: Parameters<typeof updateReminder>[1]) => updateReminder(reminder.reminder_id, changes),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["reminders"] });
    },
  });
  const active = reminder.status === "ACTIVE";

  if (editing) {
    return (
      <tr className="reminder-editing">
        <td><input type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} aria-label="Reminder time" /></td>
        <td><input value={orderId} onChange={(event) => setOrderId(event.target.value)} aria-label="Order ID" /></td>
        <td>
          <input value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} aria-label="Reminder note" />
          {update.error && <p className="reminder-error">{update.error.message}</p>}
        </td>
        <td />
        <td className="reminder-actions">
          <button className="button button-primary button-small" disabled={update.isPending || !note.trim() || !when}
            onClick={() => update.mutate({ order_id: orderId.trim(), note: note.trim(), remind_at: fromLocalInput(when) })}>Save</button>
          <button className="button button-secondary button-small" onClick={() => setEditing(false)}>Discard</button>
        </td>
      </tr>
    );
  }
  return (
    <tr className={active ? "" : "reminder-closed"}>
      <td className="mono">{formatWhen(reminder.remind_at)}</td>
      <td className="mono">{reminder.order_id}</td>
      <td>{reminder.note}{reminder.source === "assistant" && <span className="reminder-source">via AI chat</span>}</td>
      <td><span className={`due-chip due-${reminder.due_state.toLowerCase()}`}>{DUE_LABELS[reminder.due_state]}</span></td>
      <td className="reminder-actions">
        {active && (
          <>
            <button className="icon-button" title="Edit" aria-label={`Edit reminder for ${reminder.order_id}`} onClick={() => setEditing(true)}><Pencil size={15} /></button>
            <button className="icon-button" title="Mark done" aria-label={`Mark reminder for ${reminder.order_id} done`} onClick={() => update.mutate({ status: "DONE" })}><Check size={15} /></button>
            <button className="icon-button" title="Cancel reminder" aria-label={`Cancel reminder for ${reminder.order_id}`} onClick={() => update.mutate({ status: "CANCELLED" })}><X size={15} /></button>
          </>
        )}
        {update.error && !editing && <p className="reminder-error">{update.error.message}</p>}
      </td>
    </tr>
  );
}

export function RemindersPage() {
  const queryClient = useQueryClient();
  const [showClosed, setShowClosed] = useState(false);
  const [orderId, setOrderId] = useState("");
  const [note, setNote] = useState("");
  const [when, setWhen] = useState(defaultReminderTime());
  const reminders = useQuery({
    queryKey: ["reminders", showClosed],
    queryFn: () => getReminders(showClosed),
    refetchInterval: 60_000,
  });
  const create = useMutation({
    mutationFn: createReminder,
    onSuccess: () => {
      setOrderId("");
      setNote("");
      setWhen(defaultReminderTime());
      queryClient.invalidateQueries({ queryKey: ["reminders"] });
      queryClient.invalidateQueries({ queryKey: ["action-audit"] });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    create.mutate({ order_id: orderId.trim(), note: note.trim(), remind_at: fromLocalInput(when) });
  }

  return (
    <div className="page-stack">
      <section className="page-intro">
        <div><span className="eyebrow">FOLLOW-UPS</span><p>Reminders for orders. Times use your computer's clock and show up here and on the Overview page; no notifications are sent.</p></div>
      </section>
      <section className="panel filter-panel">
        <div className="filter-title"><BellPlus size={16} /><strong>New reminder</strong><span>Order must exist</span></div>
        <form className="filter-form reminder-form" onSubmit={submit}>
          <label>Order ID<input value={orderId} onChange={(event) => setOrderId(event.target.value)} placeholder="ORD-029" required /></label>
          <label>Note<input value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="What should you check?" required /></label>
          <label>When<input type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} required /></label>
          <button className="button button-primary" type="submit" disabled={create.isPending}><BellPlus size={16} /> Add reminder</button>
        </form>
        {create.error && <ErrorState message={create.error.message} />}
      </section>
      <section className="panel table-panel">
        <div className="panel-heading table-heading">
          <div><span className="eyebrow">{showClosed ? "ALL REMINDERS" : "ACTIVE REMINDERS"}</span><h2>{reminders.data?.length ?? "—"} <small>reminders</small></h2></div>
          <label className="reminder-toggle"><input type="checkbox" checked={showClosed} onChange={(event) => setShowClosed(event.target.checked)} /> Show done and cancelled</label>
        </div>
        {reminders.isLoading && <LoadingState label="Loading reminders" />}
        {reminders.error && <ErrorState message={reminders.error.message} />}
        {reminders.data && reminders.data.length === 0 && <div className="empty-row">No reminders yet. Add one above, or ask the AI assistant to prepare one.</div>}
        {reminders.data && reminders.data.length > 0 && (
          <div className="table-scroll">
            <table className="data-table reminder-table">
              <thead><tr><th>WHEN</th><th>ORDER</th><th>NOTE</th><th>STATUS</th><th /></tr></thead>
              <tbody>{reminders.data.map((reminder) => <ReminderRow key={reminder.reminder_id} reminder={reminder} />)}</tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
