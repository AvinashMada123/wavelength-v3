import { describe, it, expect } from "vitest";
import { formatDate, formatPhoneNumber, formatDuration, timeAgo } from "../utils";

// ---------------------------------------------------------------------------
// formatDate
// ---------------------------------------------------------------------------

describe("formatDate", () => {
  it("returns empty string for null", () => {
    expect(formatDate(null)).toBe("");
  });

  it("returns empty string for undefined", () => {
    expect(formatDate(undefined)).toBe("");
  });

  it("returns empty string for empty string", () => {
    expect(formatDate("")).toBe("");
  });

  it("returns empty string for invalid date", () => {
    expect(formatDate("not-a-date")).toBe("");
  });

  it("formats a valid ISO date string", () => {
    const result = formatDate("2026-03-15T10:30:00Z");
    expect(result).toMatch(/Mar/);
    expect(result).toMatch(/15/);
    expect(result).toMatch(/2026/);
  });

  it("formats a date-only string", () => {
    const result = formatDate("2026-01-01");
    expect(result).toMatch(/Jan/);
    expect(result).toMatch(/1/);
    expect(result).toMatch(/2026/);
  });
});

// ---------------------------------------------------------------------------
// formatPhoneNumber
// ---------------------------------------------------------------------------

describe("formatPhoneNumber", () => {
  it("returns empty string for null", () => {
    expect(formatPhoneNumber(null)).toBe("");
  });

  it("returns empty string for undefined", () => {
    expect(formatPhoneNumber(undefined)).toBe("");
  });

  it("returns empty string for empty string", () => {
    expect(formatPhoneNumber("")).toBe("");
  });

  it("formats a 10-digit number as (XXX) XXX-XXXX", () => {
    expect(formatPhoneNumber("3177127687")).toBe("(317) 712-7687");
  });

  it("returns original for numbers longer than 10 digits", () => {
    expect(formatPhoneNumber("+919609775259")).toBe("+919609775259");
  });

  it("returns original for numbers shorter than 10 digits", () => {
    expect(formatPhoneNumber("12345")).toBe("12345");
  });

  it("strips non-digits before formatting", () => {
    expect(formatPhoneNumber("(317) 712-7687")).toBe("(317) 712-7687");
  });

  it("handles already-formatted number with +1 prefix", () => {
    expect(formatPhoneNumber("+13177127687")).toBe("+13177127687");
  });
});

// ---------------------------------------------------------------------------
// formatDuration
// ---------------------------------------------------------------------------

describe("formatDuration", () => {
  it.each([
    [null, "0s"],
    [undefined, "0s"],
    [0, "0s"],
    [-5, "0s"],
  ])("returns '0s' for %s", (input, expected) => {
    expect(formatDuration(input as any)).toBe(expected);
  });

  it("formats seconds under 60", () => {
    expect(formatDuration(45)).toBe("45s");
  });

  it("formats 1 second", () => {
    expect(formatDuration(1)).toBe("1s");
  });

  it("formats exactly 60 seconds as minutes", () => {
    expect(formatDuration(60)).toBe("1m");
  });

  it("formats minutes and seconds", () => {
    expect(formatDuration(90)).toBe("1m 30s");
  });

  it("formats exact minutes without trailing seconds", () => {
    expect(formatDuration(120)).toBe("2m");
  });

  it("formats large durations", () => {
    expect(formatDuration(3661)).toBe("61m 1s");
  });

  it("rounds fractional seconds", () => {
    expect(formatDuration(30.7)).toBe("31s");
  });

  it("rounds fractional seconds in minutes", () => {
    expect(formatDuration(61.4)).toBe("1m 1s");
  });
});

// ---------------------------------------------------------------------------
// timeAgo
// ---------------------------------------------------------------------------

describe("timeAgo", () => {
  it("returns 'just now' for recent timestamp", () => {
    const now = new Date().toISOString();
    expect(timeAgo(now)).toBe("just now");
  });

  it("returns minutes ago", () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    expect(timeAgo(fiveMinAgo)).toBe("5m ago");
  });

  it("returns hours ago", () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    expect(timeAgo(threeHoursAgo)).toBe("3h ago");
  });

  it("returns days ago", () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
    expect(timeAgo(twoDaysAgo)).toBe("2d ago");
  });

  it.each([
    [59 * 1000, "just now"],
    [60 * 1000, "1m ago"],
    [59 * 60 * 1000, "59m ago"],
    [60 * 60 * 1000, "1h ago"],
    [23 * 60 * 60 * 1000, "23h ago"],
    [24 * 60 * 60 * 1000, "1d ago"],
  ])("boundary: %ims ago → '%s'", (offsetMs, expected) => {
    const ago = new Date(Date.now() - offsetMs).toISOString();
    expect(timeAgo(ago)).toBe(expected);
  });
});
