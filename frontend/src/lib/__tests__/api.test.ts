/**
 * Tests for src/lib/api.ts — apiFetch, token refresh, error extraction,
 * and convenience wrappers.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// Mock localStorage
const store: Record<string, string> = {};
const localStorageMock = {
  getItem: vi.fn((key: string) => store[key] ?? null),
  setItem: vi.fn((key: string, value: string) => {
    store[key] = value;
  }),
  removeItem: vi.fn((key: string) => {
    delete store[key];
  }),
  clear: vi.fn(() => {
    Object.keys(store).forEach((k) => delete store[k]);
  }),
  get length() {
    return Object.keys(store).length;
  },
  key: vi.fn((_: number) => null),
};
vi.stubGlobal("localStorage", localStorageMock);

// Mock window.location
const locationMock = { href: "" };
vi.stubGlobal("window", { localStorage: localStorageMock, location: locationMock });

import {
  apiFetch,
  fetchBots,
  fetchBot,
  fetchCallLogs,
  getRecordingUrl,
} from "../api";

beforeEach(() => {
  mockFetch.mockReset();
  localStorageMock.clear();
  locationMock.href = "";
});

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
    headers: new Headers(),
  } as unknown as Response;
}

function textResponse(body: string, status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.reject(new Error("not json")),
    text: () => Promise.resolve(body),
    headers: new Headers(),
  } as unknown as Response;
}

// ---------------------------------------------------------------------------
// apiFetch — happy path
// ---------------------------------------------------------------------------

describe("apiFetch", () => {
  it("adds Authorization header when token exists", async () => {
    localStorageMock.setItem("access_token", "tok-123");
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));

    await apiFetch("/api/test");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/test",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer tok-123",
          "Content-Type": "application/json",
        }),
      })
    );
  });

  it("omits Authorization when no token", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));

    await apiFetch("/api/test");

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.Authorization).toBeUndefined();
  });

  it("returns parsed JSON on success", async () => {
    localStorageMock.setItem("access_token", "tok");
    mockFetch.mockResolvedValueOnce(jsonResponse({ items: [1, 2, 3] }));

    const result = await apiFetch<{ items: number[] }>("/api/data");
    expect(result).toEqual({ items: [1, 2, 3] });
  });

  it("returns undefined for 204 No Content", async () => {
    localStorageMock.setItem("access_token", "tok");
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: new Headers(),
    } as unknown as Response);

    const result = await apiFetch("/api/delete-thing");
    expect(result).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// apiFetch — error handling
// ---------------------------------------------------------------------------

describe("apiFetch error handling", () => {
  it("throws with detail from JSON error body", async () => {
    localStorageMock.setItem("access_token", "tok");
    mockFetch.mockResolvedValueOnce(
      textResponse(JSON.stringify({ detail: "Not found" }), 404)
    );

    await expect(apiFetch("/api/missing")).rejects.toThrow("Not found");
  });

  it("throws with message from JSON error body", async () => {
    localStorageMock.setItem("access_token", "tok");
    mockFetch.mockResolvedValueOnce(
      textResponse(JSON.stringify({ message: "Bad request" }), 400)
    );

    await expect(apiFetch("/api/bad")).rejects.toThrow("Bad request");
  });

  it("throws with raw body when not JSON", async () => {
    localStorageMock.setItem("access_token", "tok");
    mockFetch.mockResolvedValueOnce(textResponse("Internal Server Error", 500));

    await expect(apiFetch("/api/broken")).rejects.toThrow(
      "Internal Server Error"
    );
  });

  it("throws with fallback message for empty body", async () => {
    localStorageMock.setItem("access_token", "tok");
    mockFetch.mockResolvedValueOnce(textResponse("", 500));

    await expect(apiFetch("/api/empty")).rejects.toThrow("Request failed (500)");
  });

  it("propagates network errors when fetch throws", async () => {
    localStorageMock.setItem("access_token", "tok");
    mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(apiFetch("/api/down")).rejects.toThrow("Failed to fetch");
  });
});

// ---------------------------------------------------------------------------
// apiFetch — 401 token refresh flow
// ---------------------------------------------------------------------------

describe("apiFetch 401 refresh", () => {
  it("retries after successful token refresh", async () => {
    localStorageMock.setItem("access_token", "expired-tok");
    localStorageMock.setItem("refresh_token", "refresh-tok");

    // First call → 401
    mockFetch.mockResolvedValueOnce(textResponse("", 401));
    // Refresh call → success
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ access_token: "new-tok" })
    );
    // Retry call → success
    mockFetch.mockResolvedValueOnce(jsonResponse({ data: "refreshed" }));

    const result = await apiFetch<{ data: string }>("/api/protected");
    expect(result).toEqual({ data: "refreshed" });
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      "access_token",
      "new-tok"
    );
  });

  it("redirects to login when refresh fails", async () => {
    localStorageMock.setItem("access_token", "expired");
    localStorageMock.setItem("refresh_token", "bad-refresh");

    // First call → 401
    mockFetch.mockResolvedValueOnce(textResponse("", 401));
    // Refresh call → fails
    mockFetch.mockResolvedValueOnce(textResponse("", 401));

    await expect(apiFetch("/api/protected")).rejects.toThrow(
      "Authentication expired"
    );
    expect(locationMock.href).toBe("/login");
    expect(localStorageMock.removeItem).toHaveBeenCalledWith("access_token");
    expect(localStorageMock.removeItem).toHaveBeenCalledWith("refresh_token");
    expect(localStorageMock.removeItem).toHaveBeenCalledWith("auth_user");
  });

  it("redirects to login when no refresh token", async () => {
    localStorageMock.setItem("access_token", "expired");

    mockFetch.mockResolvedValueOnce(textResponse("", 401));

    await expect(apiFetch("/api/protected")).rejects.toThrow(
      "Authentication expired"
    );
    expect(locationMock.href).toBe("/login");
  });

  it("throws when retry after refresh also fails", async () => {
    localStorageMock.setItem("access_token", "expired");
    localStorageMock.setItem("refresh_token", "good");

    // First → 401
    mockFetch.mockResolvedValueOnce(textResponse("", 401));
    // Refresh → success
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ access_token: "new-tok" })
    );
    // Retry → still fails
    mockFetch.mockResolvedValueOnce(
      textResponse(JSON.stringify({ detail: "Forbidden" }), 403)
    );

    await expect(apiFetch("/api/protected")).rejects.toThrow("Forbidden");
  });
});

// ---------------------------------------------------------------------------
// Convenience wrappers
// ---------------------------------------------------------------------------

describe("convenience API wrappers", () => {
  beforeEach(() => {
    localStorageMock.setItem("access_token", "tok");
  });

  it("fetchBots calls /api/bots", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse([]));
    await fetchBots();
    expect(mockFetch.mock.calls[0][0]).toBe("/api/bots");
  });

  it("fetchBot calls /api/bots/:id", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ id: "b1" }));
    await fetchBot("b1");
    expect(mockFetch.mock.calls[0][0]).toBe("/api/bots/b1");
  });

  it("fetchCallLogs builds query string", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));
    await fetchCallLogs({ botId: "bot-1", goalOutcome: "completed" });
    expect(mockFetch.mock.calls[0][0]).toBe(
      "/api/calls?bot_id=bot-1&goal_outcome=completed"
    );
  });

  it("fetchCallLogs without params has no query string", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));
    await fetchCallLogs();
    expect(mockFetch.mock.calls[0][0]).toBe("/api/calls");
  });

  it("fetchCallLogs passes limit and offset for pagination", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 100 }));
    const result = await fetchCallLogs({ limit: 25, offset: 50 });
    expect(mockFetch.mock.calls[0][0]).toBe("/api/calls?limit=25&offset=50");
    expect(result.total).toBe(100);
  });
});

// ---------------------------------------------------------------------------
// getRecordingUrl (sync, no fetch)
// ---------------------------------------------------------------------------

describe("getRecordingUrl", () => {
  it("includes token as query param", () => {
    localStorageMock.setItem("access_token", "my-token");
    expect(getRecordingUrl("sid-1")).toBe(
      "/api/calls/sid-1/recording?token=my-token"
    );
  });

  it("omits token param when no token", () => {
    localStorageMock.clear();
    expect(getRecordingUrl("sid-1")).toBe("/api/calls/sid-1/recording");
  });
});
