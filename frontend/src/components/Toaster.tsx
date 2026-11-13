import { useEffect, useState } from "react";
import { Check, CircleAlert, X } from "lucide-react";

export interface ToastInput {
  tone?: "success" | "warning";
  title: string;
  detail?: string;
}

interface Toast extends Required<Omit<ToastInput, "detail">> {
  id: number;
  detail?: string;
}

const TOAST_EVENT = "copilot:toast";
const VISIBLE_MS = 4000;
let nextId = 1;

/** Show a short confirmation in the corner of the screen. Safe to call from anywhere. */
export function showToast(input: ToastInput) {
  window.dispatchEvent(new CustomEvent<ToastInput>(TOAST_EVENT, { detail: input }));
}

export function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const timers = new Set<number>();
    const handle = (event: Event) => {
      const input = (event as CustomEvent<ToastInput>).detail;
      const toast: Toast = { id: nextId++, tone: input.tone ?? "success", title: input.title, detail: input.detail };
      setToasts((current) => [...current.slice(-2), toast]);
      const timer = window.setTimeout(() => {
        setToasts((current) => current.filter((item) => item.id !== toast.id));
        timers.delete(timer);
      }, VISIBLE_MS);
      timers.add(timer);
    };
    window.addEventListener(TOAST_EVENT, handle);
    return () => {
      window.removeEventListener(TOAST_EVENT, handle);
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, []);

  const dismiss = (id: number) => setToasts((current) => current.filter((item) => item.id !== id));

  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div className={`toast toast-${toast.tone}`} key={toast.id}>
          <span className="toast-icon" aria-hidden="true">
            {toast.tone === "success" ? <Check size={15} strokeWidth={3} /> : <CircleAlert size={15} />}
          </span>
          <div className="toast-copy">
            <strong>{toast.title}</strong>
            {toast.detail && <p>{toast.detail}</p>}
          </div>
          <button className="toast-close" onClick={() => dismiss(toast.id)} aria-label="Dismiss notification"><X size={14} /></button>
          <span className="toast-timer" style={{ animationDuration: `${VISIBLE_MS}ms` }} aria-hidden="true" />
        </div>
      ))}
    </div>
  );
}
