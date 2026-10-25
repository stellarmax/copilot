import type { ReminderDueState } from "./api";

/** Value for an <input type="datetime-local"> in the user's local time. */
export function toLocalInput(iso: string): string {
  const date = new Date(iso);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

/** A datetime-local value is local wall time; send it to the API as a timezone-aware instant. */
export function fromLocalInput(value: string): string {
  return new Date(value).toISOString();
}

/** Tomorrow at 09:00 local time, the default for a new reminder. */
export function defaultReminderTime(): string {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(9, 0, 0, 0);
  return toLocalInput(date.toISOString());
}

export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export const DUE_LABELS: Record<ReminderDueState, string> = {
  OVERDUE: "Overdue",
  DUE_SOON: "Due within 24h",
  UPCOMING: "Upcoming",
  DONE: "Done",
  CANCELLED: "Cancelled",
};
