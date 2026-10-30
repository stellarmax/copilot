import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
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
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}><App /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("sign-in gate", () => {
  it("enters the workspace right after a successful sign-in, and leaves it on sign-out", async () => {
    let signedIn = false;
    const fetchMock = vi.fn((path: string) => {
      if (path === "/api/v1/auth/me") return signedIn ? reply(200, user) : reply(401, { detail: "Please sign in." });
      if (path === "/api/v1/auth/login") { signedIn = true; return reply(200, user); }
      if (path === "/api/v1/auth/logout") { signedIn = false; return reply(200, { signed_out: true }); }
      if (path === "/health") return reply(200, { status: "ok" });
      return signedIn ? reply(200, {}) : reply(401, { detail: "Please sign in." });
    });
    renderApp(fetchMock);

    fireEvent.change(await screen.findByLabelText("E-mail"), { target: { value: "gm@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long enough 1" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Grace Ma")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Account options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
  });

  it("confirms a new account and opens AI settings", async () => {
    let signedIn = false;
    const fetchMock = vi.fn((path: string) => {
      if (path === "/api/v1/auth/me") return signedIn ? reply(200, user) : reply(401, { detail: "Please sign in." });
      if (path === "/api/v1/auth/register") { signedIn = true; return reply(200, user); }
      if (path === "/health") return reply(200, { status: "ok" });
      return new Promise(() => {});  // leave the settings panels loading
    });
    renderApp(fetchMock, "/");

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
