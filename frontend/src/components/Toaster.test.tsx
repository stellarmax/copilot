import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Toaster, showToast } from "./Toaster";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Toaster", () => {
  it("shows a confirmation, lets the user dismiss it, and hides it by itself", () => {
    vi.useFakeTimers();
    render(<Toaster />);

    act(() => showToast({ title: "Morning brief ready", detail: "3 priorities" }));
    expect(screen.getByText("Morning brief ready")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByText("Morning brief ready")).toBeNull();

    act(() => showToast({ tone: "warning", title: "Re-verified: DRIFTED" }));
    expect(screen.getByText("Re-verified: DRIFTED")).toBeTruthy();
    act(() => vi.advanceTimersByTime(4100));
    expect(screen.queryByText("Re-verified: DRIFTED")).toBeNull();
  });
});
