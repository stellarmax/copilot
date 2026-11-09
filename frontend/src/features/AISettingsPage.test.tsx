import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { AISettingsPage } from "./AISettingsPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const reply = (status: number, body: unknown) =>
  Promise.resolve({ ok: status < 400, status, statusText: "", json: async () => body });

const settings = { provider: "claude", base_url: "", model: "claude-sonnet-5-5", has_api_key: true, encryption_ready: true, updated_at: null };
const catalog = { providers: [{ id: "claude", label: "Claude (Anthropic)", models: [{ id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" }] }] };

function renderPage(testReply: () => Promise<unknown>) {
  vi.stubGlobal("fetch", vi.fn((path: string) => {
    if (path === "/api/v1/settings/ai/test") return testReply();
    if (path === "/api/v1/settings/ai") return reply(200, settings);
    if (path === "/api/v1/settings/ai/catalog") return reply(200, catalog);
    if (path === "/api/v1/settings/chat-memory") return reply(200, { enabled: false });
    if (path === "/api/v1/chat/memories") return reply(200, []);
    return reply(200, {});
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><AISettingsPage /></MemoryRouter></QueryClientProvider>);
}

describe("Test connection", () => {
  it("shows a rejected key only as an error, never as a green success note", async () => {
    const { container } = renderPage(() => reply(502, { detail: "The AI provider rejected the configured API key. Check it in AI settings." }));
    fireEvent.click(await screen.findByRole("button", { name: /Test connection/ }));

    expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("rejected the configured API key"));
    expect(container.querySelector(".settings-notice")).toBeNull();
  });

  it("shows a working connection as a green success note", async () => {
    const { container } = renderPage(() => reply(200, { status: "ok", message: "AI provider connection succeeded." }));
    fireEvent.click(await screen.findByRole("button", { name: /Test connection/ }));

    expect(await screen.findByText("AI provider connection succeeded.")).toBeTruthy();
    expect(container.querySelector(".settings-notice")).not.toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
