import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { RemindersPage } from "./RemindersPage";
import { ReminderNotifier } from "../components/ReminderNotifier";
import type { Reminder, ReminderSuggestions } from "../lib/api";
import { describeDaysToDue, tomorrowMorning } from "../lib/reminders";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const reply = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => body });

const reminder: Reminder = {
  reminder_id: "REM-0001",
  order_id: "ORD-101",
  note: "Check knitting progress",
  remind_at: new Date(Date.now() + 2 * 3_600_000).toISOString(),
  status: "ACTIVE",
  source: "web",
  due_state: "DUE_SOON",
  repeat: "WEEKLY",
  claim_id: null,
  last_completed_at: null,
  order_context: { customer: "TrendCart", status: "IN_PROGRESS", current_stage: "KNITTING", due_date: "2026-04-04", days_to_due: 3, risk_level: "HIGH", suggest_close: false },
  created_at: "2026-11-06T00:00:00Z",
  updated_at: "2026-11-06T00:00:00Z",
};

const suggestions: ReminderSuggestions = {
  business_as_of_date: "2026-04-01",
  total_suggestions: 1,
  dismissed_count: 0,
  rule_notice: "Thresholds are team assumptions.",
  suggestions: [{
    order_id: "ORD-102", customer: "TrendCart", product: "Beanie", pieces: 300, current_stage: "PACKING",
    due_date: "2026-04-05", days_to_due: 4, risk_level: "HIGH", rules_triggered: ["DEADLINE_APPROACHING"],
    reasons: ["due in 4 days"], suggested_note: "Follow up on ORD-102 (TrendCart): due in 4 days.",
    claim_id: "CLM-20260401-RISK-001-abcdef12",
  }],
};

function renderPage(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><RemindersPage onTrace={() => {}} /></QueryClientProvider>);
}

function api(overrides: Record<string, (init?: RequestInit) => unknown> = {}) {
  return vi.fn((path: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${path}`;
    if (overrides[key]) return reply(overrides[key](init));
    if (key === "GET /api/v1/reminders/suggestions") return reply(suggestions);
    if (key === "GET /api/v1/reminders") return reply([reminder]);
    return reply({});
  });
}

describe("RemindersPage", () => {
  it("shows the order's current state and the repeat rule", async () => {
    renderPage(api());
    expect(await screen.findByText("due in 3 days")).toBeTruthy();
    expect(screen.getByText("Every week", { selector: "small" })).toBeTruthy();
    expect(screen.getAllByText("HIGH").length).toBeGreaterThan(0);
  });

  it("turns a risk suggestion into a reminder that keeps its evidence", async () => {
    const fetchMock = api({ "POST /api/v1/reminders": () => ({ status: "CREATED" }) });
    renderPage(fetchMock);
    fireEvent.click(await screen.findByRole("button", { name: /Remind me tomorrow 9:00/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([path, init]) => path === "/api/v1/reminders" && init?.method === "POST")).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([path, call]) => path === "/api/v1/reminders" && call?.method === "POST")!;
    const body = JSON.parse(String(init?.body));
    expect(body).toMatchObject({ order_id: "ORD-102", claim_id: "CLM-20260401-RISK-001-abcdef12" });
    expect(new Date(body.remind_at).getHours()).toBe(9);
  });

  it("snoozes a reminder by one hour", async () => {
    const fetchMock = api({ "PATCH /api/v1/reminders/REM-0001": () => ({ status: "UPDATED" }) });
    renderPage(fetchMock);
    fireEvent.click(await screen.findByRole("button", { name: "Snooze reminder for ORD-101" }));
    const before = Date.now();
    fireEvent.click(screen.getByRole("menuitem", { name: "1 hour" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([, call]) => call?.method === "PATCH")!;
    const until = Date.parse(JSON.parse(String(init?.body)).remind_at);
    expect(until - before).toBeGreaterThanOrEqual(3_599_000);
    expect(until - before).toBeLessThan(3_700_000);
  });
});

describe("ReminderNotifier", () => {
  it("announces each due reminder once and shows the count in the tab title", () => {
    const shown: string[] = [];
    class FakeNotification {
      static permission = "granted";
      onclick: (() => void) | null = null;
      constructor(title: string) { shown.push(title); }
      close() {}
    }
    vi.stubGlobal("Notification", FakeNotification);
    document.title = "Fieldwork | Operations Co-Pilot";
    const due = [{ ...reminder, remind_at: new Date(Date.now() - 1000).toISOString(), due_state: "OVERDUE" as const }];
    const { rerender } = render(<MemoryRouter><ReminderNotifier due={due} userId="u1" /></MemoryRouter>);
    expect(shown).toEqual(["Reminder · ORD-101"]);
    expect(document.title).toBe("(1) Fieldwork | Operations Co-Pilot");
    rerender(<MemoryRouter><ReminderNotifier due={[...due]} userId="u1" /></MemoryRouter>);
    expect(shown).toHaveLength(1);
    rerender(<MemoryRouter><ReminderNotifier due={[]} userId="u1" /></MemoryRouter>);
    expect(document.title).toBe("Fieldwork | Operations Co-Pilot");
  });
});

describe("reminder helpers", () => {
  it("computes snooze targets and due-date wording", () => {
    const morning = tomorrowMorning(new Date(2026, 10, 6, 22, 30));
    expect([morning.getDate(), morning.getHours(), morning.getMinutes()]).toEqual([7, 9, 0]);
    expect(describeDaysToDue(0)).toBe("due today");
    expect(describeDaysToDue(1)).toBe("due in 1 day");
    expect(describeDaysToDue(-4)).toBe("4 days overdue");
  });
});
