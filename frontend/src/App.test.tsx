import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { StrictMode } from "react";
import App from "./App";
import { greeting } from "./lib/greeting";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const user = { user_id: "u1", email: "gm@example.com", display_name: "Grace Ma" };
const reply = (status: number, body: unknown) =>
  Promise.resolve({ ok: status < 400, status, statusText: "", json: async () => body });

function renderApp(fetchMock: ReturnType<typeof vi.fn>, path = "/settings") {
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // StrictMode, as in main.tsx, so development-only double effects are covered too.
  return render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}><App /></MemoryRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}

describe("signed-out workspace", () => {
  const onlyPublicCalls = (fetchMock: ReturnType<typeof vi.fn>) =>
    fetchMock.mock.calls.map(([path]) => path).every((path) => path === "/api/v1/auth/me" || path === "/health");

  it("opens every page without data, shows the data right after signing in, and none after signing out", async () => {
    let signedIn = false;
    const fetchMock = vi.fn((path: string) => {
      if (path === "/api/v1/auth/me") return signedIn ? reply(200, user) : reply(401, { detail: "Please sign in." });
      if (path === "/api/v1/auth/login") { signedIn = true; return reply(200, user); }
      if (path === "/api/v1/auth/logout") { signedIn = false; return reply(200, { signed_out: true }); }
      if (path === "/health") return reply(200, { status: "ok" });
      return signedIn ? new Promise(() => {}) : reply(401, { detail: "Please sign in." });
    });
    renderApp(fetchMock, "/orders");

    expect(await screen.findByRole("heading", { name: "Order book" })).toBeTruthy();  // the real page
    expect((await screen.findAllByText("Sign in to see data and use the AI assistant.")).length).toBeGreaterThan(0);
    expect(onlyPublicCalls(fetchMock)).toBe(true);  // no data request is even sent

    fireEvent.click(screen.getAllByRole("link", { name: /Sign in/ })[0]);
    fireEvent.change(await screen.findByLabelText("E-mail"), { target: { value: "gm@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long enough 1" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Grace Ma")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Order book" })).toBeTruthy();  // back on the same page
    expect(screen.queryByText("Sign in to see data and use the AI assistant.")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Account options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    expect((await screen.findAllByText("Sign in to see data and use the AI assistant.")).length).toBeGreaterThan(0);
  });

  it("asks the visitor to sign in for the brief, and in the AI chat", async () => {
    Element.prototype.scrollIntoView = vi.fn();  // not implemented in jsdom
    const fetchMock = vi.fn((path: string) => {
      if (path === "/api/v1/auth/me") return reply(401, { detail: "Please sign in." });
      if (path === "/health") return reply(200, { status: "ok" });
      return reply(401, { detail: "Please sign in." });
    });
    renderApp(fetchMock, "/");

    fireEvent.click(await screen.findByRole("button", { name: /Generate morning brief/ }));
    // The brief stays on the Overview and shows the sign-in prompt instead of results.
    expect((await screen.findAllByText("Sign in to see data and use the AI assistant.")).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Operations overview" })).toBeTruthy();

    // The chat box still opens the AI chat, which shows the question and the prompt.
    const askBox = screen.getByLabelText("Ask an operations question");
    fireEvent.change(askBox, { target: { value: "Which orders need attention?" } });
    fireEvent.submit(askBox.closest("form")!);
    expect(await screen.findByText("Which orders need attention?", { selector: ".user-bubble" })).toBeTruthy();
    expect(screen.getAllByText("Sign in to see data and use the AI assistant.")).toHaveLength(1);  // shown once
    expect(onlyPublicCalls(fetchMock)).toBe(true);  // neither the brief nor the AI was called
  });

  it("registers from the sign-in page and confirms the new account on AI settings", async () => {
    let signedIn = false;
    const fetchMock = vi.fn((path: string) => {
      if (path === "/api/v1/auth/me") return signedIn ? reply(200, user) : reply(401, { detail: "Please sign in." });
      if (path === "/api/v1/auth/register") { signedIn = true; return reply(200, user); }
      if (path === "/health") return reply(200, { status: "ok" });
      return new Promise(() => {});  // leave the settings panels loading
    });
    renderApp(fetchMock, "/");

    fireEvent.click((await screen.findAllByRole("link", { name: /Sign in/ }))[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Create an account" }));
    fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: "gm@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long enough 1" } });
    fireEvent.click(screen.getByRole("button", { name: /Create account/ }));

    expect(await screen.findByText(/Account created/)).toBeTruthy();
  });
});

describe("display name", () => {
  it("can be changed from the account menu", async () => {
    let current = { ...user };
    const fetchMock = vi.fn((path: string, init?: RequestInit) => {
      if (path === "/api/v1/auth/me" && init?.method === "PATCH") {
        current = { ...current, ...JSON.parse(String(init.body)) };
        return reply(200, current);
      }
      if (path === "/api/v1/auth/me") return reply(200, current);
      if (path === "/health") return reply(200, { status: "ok" });
      return new Promise(() => {});
    });
    renderApp(fetchMock);

    fireEvent.click(await screen.findByRole("button", { name: "Account options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Change display name/ }));
    fireEvent.change(screen.getByLabelText(/Display name/), { target: { value: "Grace" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Grace")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("greeting", () => {
  it("uses the time of day and the account name", () => {
    expect(greeting("Grace Ma", new Date(2026, 9, 30, 8))).toBe("Good morning, Grace Ma");
    expect(greeting("Grace Ma", new Date(2026, 9, 30, 14))).toBe("Good afternoon, Grace Ma");
    expect(greeting(" ", new Date(2026, 9, 30, 21))).toBe("Good evening");
  });
});
