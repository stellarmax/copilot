import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PendingActionCard } from "./ChatPage";
import type { PendingAction } from "../lib/api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const action: PendingAction = {
  confirmation_token: "tok-123",
  prepared_at: "2026-10-25T10:00:00Z",
  preview: {
    action_type: "create_reminder",
    target: "ORD-029",
    payload: { message: "Check knitting progress", remind_at: "2026-10-30T01:00:00+00:00" },
    claim_ids: [],
  },
};

function renderCard(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><PendingActionCard action={action} /></QueryClientProvider>);
}

const json = (body: unknown) => Promise.resolve({ ok: true, json: async () => body });

describe("PendingActionCard", () => {
  it("shows the preview and saves nothing until Confirm is clicked", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/v1/actions" && !init?.method) return json([]);
      return json({ status: "CONFIRMED" });
    });
    renderCard(fetchMock);

    expect(screen.getByText("Check knitting progress")).toBeTruthy();
    expect(screen.getByText("ORD-029")).toBeTruthy();
    expect(screen.getByText("Needs your confirmation")).toBeTruthy();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(screen.getByText(/Reminder saved/)).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/actions/tok-123/confirm", expect.objectContaining({ method: "POST" }));
  });

  it("shows the recorded state after a reload instead of the buttons", async () => {
    renderCard(vi.fn(() => json([{ confirmation_token: "tok-123", status: "CANCELLED" }])));
    await waitFor(() => expect(screen.getByText(/Cancelled. Nothing was saved./)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /confirm/i })).toBeNull();
  });
});
