import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ApiError } from "./api";

describe("apiFetch", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns a successful JSON response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "ok" }),
    }));

    await expect(apiFetch<{ status: string }>("/health")).resolves.toEqual({ status: "ok" });
  });

  it("surfaces structured API errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: async () => ({ detail: { error: "Unsupported query parameter(s)" } }),
    }));

    await expect(apiFetch("/api/v1/orders")).rejects.toBeInstanceOf(ApiError);
    await expect(apiFetch("/api/v1/orders")).rejects.toMatchObject({ status: 422 });
  });

  it("shows the readable message from a tool error envelope", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: async () => ({
        detail: {
          result_status: "INVALID_INPUT",
          error: { code: "INVALID_DATE_RANGE", message: "start_date must not be after end_date" },
        },
      }),
    }));

    await expect(apiFetch("/api/v1/production")).rejects.toMatchObject({
      message: "start_date must not be after end_date",
    });
  });
});