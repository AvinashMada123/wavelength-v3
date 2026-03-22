import { describe, it, expect } from "vitest";
import {
  escapeCsv,
  fmtDate,
  formatTranscript,
  callToRow,
} from "../call-logs-export";
import type { CallLog } from "@/types/api";

// ---------------------------------------------------------------------------
// escapeCsv
// ---------------------------------------------------------------------------

describe("escapeCsv", () => {
  it("returns simple value as-is", () => {
    expect(escapeCsv("hello")).toBe("hello");
  });

  it("wraps value with commas in quotes", () => {
    expect(escapeCsv("hello,world")).toBe('"hello,world"');
  });

  it("doubles quotes and wraps value with double quotes", () => {
    expect(escapeCsv('he said "hi"')).toBe('"he said ""hi"""');
  });

  it("wraps value with newlines in quotes", () => {
    expect(escapeCsv("line1\nline2")).toBe('"line1\nline2"');
  });

  it("returns empty string as-is", () => {
    expect(escapeCsv("")).toBe("");
  });

  it("handles all special chars combined", () => {
    expect(escapeCsv('a,b"c\nd')).toBe('"a,b""c\nd"');
  });
});

// ---------------------------------------------------------------------------
// fmtDate
// ---------------------------------------------------------------------------

describe("fmtDate", () => {
  it("returns empty string for null", () => {
    expect(fmtDate(null)).toBe("");
  });

  it("returns empty string for empty string", () => {
    expect(fmtDate("")).toBe("");
  });

  it("formats a valid ISO date with recognizable parts", () => {
    const result = fmtDate("2026-03-15T10:30:00Z");
    expect(result).toMatch(/Mar/);
    expect(result).toMatch(/15/);
    expect(result).toMatch(/2026/);
  });
});

// ---------------------------------------------------------------------------
// formatTranscript
// ---------------------------------------------------------------------------

describe("formatTranscript", () => {
  it("returns empty string for undefined", () => {
    expect(formatTranscript(undefined)).toBe("");
  });

  it("returns empty string for empty array", () => {
    expect(formatTranscript([])).toBe("");
  });

  it("formats AI and User entries correctly", () => {
    const transcript = [
      { role: "assistant", content: "Hello!" },
      { role: "user", content: "Hi there" },
      { role: "assistant", content: "How can I help?" },
    ];
    const result = formatTranscript(transcript);
    expect(result).toBe("AI: Hello!\nUser: Hi there\nAI: How can I help?");
  });

  it("single entry has no trailing newline", () => {
    const result = formatTranscript([{ role: "assistant", content: "Hi" }]);
    expect(result).toBe("AI: Hi");
    expect(result).not.toMatch(/\n$/);
  });
});

// ---------------------------------------------------------------------------
// callToRow — bot_name inclusion
// ---------------------------------------------------------------------------

describe("callToRow", () => {
  const baseCall: CallLog = {
    id: "1",
    bot_id: "bot-1",
    bot_name: "Sales Bot",
    call_sid: "sid-1",
    contact_name: "John",
    contact_phone: "+911234567890",
    ghl_contact_id: null,
    status: "completed",
    outcome: "success",
    call_duration: 120,
    summary: "Good call",
    started_at: "2026-03-15T10:00:00Z",
    ended_at: "2026-03-15T10:02:00Z",
    created_at: "2026-03-15T10:00:00Z",
  };

  it("includes bot_name as the first column", () => {
    const row = callToRow(baseCall);
    expect(row[0]).toBe("Sales Bot");
  });

  it("uses empty string when bot_name is null", () => {
    const row = callToRow({ ...baseCall, bot_name: null });
    expect(row[0]).toBe("");
  });

  it("has contact_name as the second column", () => {
    const row = callToRow(baseCall);
    expect(row[1]).toBe("John");
  });
});
