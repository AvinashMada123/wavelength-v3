/**
 * Tests for query key factories from hooks.
 * These are pure functions that generate stable cache keys for TanStack Query.
 */

import { describe, it, expect } from "vitest";
import { callKeys } from "../use-calls";
import { botKeys } from "../use-bots";
import { billingKeys } from "../use-billing";

// ---------------------------------------------------------------------------
// callKeys
// ---------------------------------------------------------------------------

describe("callKeys", () => {
  it("all key is stable", () => {
    expect(callKeys.all).toEqual(["calls"]);
    // Same reference
    expect(callKeys.all).toBe(callKeys.all);
  });

  it("list key includes filters", () => {
    const key = callKeys.list({ botId: "b1", goalOutcome: "confirmed" });
    expect(key).toEqual(["calls", "list", { botId: "b1", goalOutcome: "confirmed" }]);
  });

  it("list key with empty filters", () => {
    const key = callKeys.list({});
    expect(key).toEqual(["calls", "list", {}]);
  });

  it("detail key includes id", () => {
    const key = callKeys.detail("call-123");
    expect(key).toEqual(["calls", "call-123"]);
  });

  it("health key is stable", () => {
    expect(callKeys.health).toEqual(["health"]);
  });

  it("different filters produce different keys", () => {
    const k1 = callKeys.list({ botId: "a" });
    const k2 = callKeys.list({ botId: "b" });
    expect(k1).not.toEqual(k2);
  });
});

// ---------------------------------------------------------------------------
// botKeys
// ---------------------------------------------------------------------------

describe("botKeys", () => {
  it("all key is stable", () => {
    expect(botKeys.all).toEqual(["bots"]);
  });

  it("detail key includes id", () => {
    expect(botKeys.detail("bot-1")).toEqual(["bots", "bot-1"]);
  });

  it("different ids produce different keys", () => {
    expect(botKeys.detail("a")).not.toEqual(botKeys.detail("b"));
  });
});

// ---------------------------------------------------------------------------
// billingKeys
// ---------------------------------------------------------------------------

describe("billingKeys", () => {
  it("balance key is stable", () => {
    expect(billingKeys.balance).toEqual(["billing", "balance"]);
  });

  it("transactions key includes params", () => {
    const key = billingKeys.transactions({ page: 2, type: "usage" });
    expect(key).toEqual(["billing", "transactions", { page: 2, type: "usage" }]);
  });

  it("transactions key without params", () => {
    const key = billingKeys.transactions();
    expect(key).toEqual(["billing", "transactions", undefined]);
  });

  it("orgBalances key is stable", () => {
    expect(billingKeys.orgBalances).toEqual(["billing", "org-balances"]);
  });
});
