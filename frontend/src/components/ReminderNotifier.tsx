import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { Reminder } from "../lib/api";

const MAX_REMEMBERED = 200;

export function notificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

function readSeen(key: string): string[] {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) ?? "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function writeSeen(key: string, seen: string[]) {
  try {
    window.localStorage.setItem(key, JSON.stringify(seen.slice(-MAX_REMEMBERED)));
  } catch {
    // Private windows may block storage; worst case a reminder is announced twice.
  }
}

/**
 * Shows the due count in the tab title and a desktop notification when a reminder comes due.
 * Works while the app is open in a tab; nothing is sent by e-mail or to other devices.
 */
export function ReminderNotifier({ due, userId }: { due: Reminder[]; userId: string }) {
  const navigate = useNavigate();
  const baseTitle = useRef(document.title.replace(/^\(\d+\) /, ""));

  useEffect(() => {
    document.title = due.length > 0 ? `(${due.length}) ${baseTitle.current}` : baseTitle.current;
  }, [due.length]);

  useEffect(() => () => {
    document.title = baseTitle.current;
  }, []);

  useEffect(() => {
    if (!notificationsSupported() || Notification.permission !== "granted") return;
    const key = `copilot.notified.${userId}`;
    const seen = readSeen(key);
    // A snoozed or repeating reminder is announced again at its new time.
    const fresh = due.filter((item) => !seen.includes(`${item.reminder_id}@${item.remind_at}`));
    if (fresh.length === 0) return;
    const open = (notification: Notification) => {
      notification.onclick = () => {
        window.focus();
        navigate("/reminders");
        notification.close();
      };
    };
    if (fresh.length > 3) {
      open(new Notification(`${fresh.length} reminders are due`, { body: "Open the Reminders page to review them.", tag: "copilot-reminders" }));
    } else {
      for (const item of fresh) {
        open(new Notification(`Reminder · ${item.order_id}`, { body: item.note, tag: item.reminder_id }));
      }
    }
    writeSeen(key, [...seen, ...fresh.map((item) => `${item.reminder_id}@${item.remind_at}`)]);
  }, [due, userId, navigate]);

  return null;
}
