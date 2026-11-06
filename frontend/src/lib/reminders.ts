import type { ReminderDueState, ReminderRepeat } from "./api";

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

/** Tomorrow at 09:00 local time. */
export function tomorrowMorning(now = new Date()): Date {
  const date = new Date(now);
  date.setDate(date.getDate() + 1);
  date.setHours(9, 0, 0, 0);
  return date;
}

/** Tomorrow at 09:00 local time, the default for a new reminder. */
export function defaultReminderTime(): string {
  return toLocalInput(tomorrowMorning().toISOString());
}

export const SNOOZE_OPTIONS: { label: string; until: (now: Date) => Date }[] = [
  { label: "1 hour", until: (now) => new Date(now.getTime() + 60 * 60_000) },
  { label: "3 hours", until: (now) => new Date(now.getTime() + 3 * 60 * 60_000) },
  { label: "Tomorrow 9:00", until: tomorrowMorning },
];

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

export const REPEAT_LABELS: Record<ReminderRepeat, string> = {
  NONE: "Once",
  DAILY: "Every day",
  WEEKLY: "Every week",
};

/** "due in 3 days" / "due today" / "4 days overdue", counted on the business date. */
export function describeDaysToDue(days: number | null): string {
  if (days === null) return "";
  if (days === 0) return "due today";
  if (days < 0) return `${-days} day${days === -1 ? "" : "s"} overdue`;
  return `due in ${days} day${days === 1 ? "" : "s"}`;
}
