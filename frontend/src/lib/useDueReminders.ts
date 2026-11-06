import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getReminders, type Reminder } from "./api";

/**
 * Active reminders and the ones that are due now.
 *
 * Polling alone would show a reminder up to a minute late, so a timer also wakes exactly when the
 * next reminder comes due.
 */
export function useDueReminders(): { reminders: Reminder[]; due: Reminder[] } {
  const reminders = useQuery({ queryKey: ["reminders", false], queryFn: () => getReminders(false), refetchInterval: 60_000 });
  const [now, setNow] = useState(() => Date.now());
  const active = reminders.data ?? [];

  useEffect(() => {
    const next = Math.min(...active.map((item) => Date.parse(item.remind_at)).filter((time) => time > now));
    const wait = Math.max(1_000, Math.min(60_000, next - Date.now()));
    const timer = window.setTimeout(() => setNow(Date.now()), wait);
    return () => window.clearTimeout(timer);
  }, [active, now]);

  return { reminders: active, due: active.filter((item) => Date.parse(item.remind_at) <= now) };
}
