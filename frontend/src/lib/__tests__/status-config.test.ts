import { describe, it, expect } from "vitest";
import {
  CALL_STATUS_CONFIG,
  CAMPAIGN_STATUS_CONFIG,
  LEAD_STATUS_COLORS,
  LEAD_QUALIFICATION_COLORS,
  INTEREST_CONFIG,
  SEVERITY_COLORS,
} from "../status-config";

// ---------------------------------------------------------------------------
// CALL_STATUS_CONFIG
// ---------------------------------------------------------------------------

describe("CALL_STATUS_CONFIG", () => {
  it.each(["initiated", "ringing", "in_progress", "completed", "failed", "error", "no_answer", "busy", "voicemail"])(
    "has call status '%s'",
    (status) => {
      expect(CALL_STATUS_CONFIG).toHaveProperty(status);
    }
  );

  it("each status has required fields", () => {
    for (const [key, config] of Object.entries(CALL_STATUS_CONFIG)) {
      expect(config).toHaveProperty("variant");
      expect(config).toHaveProperty("icon");
      expect(config).toHaveProperty("color");
      expect(typeof config.color).toBe("string");
    }
  });

  it("failed and error use destructive variant", () => {
    expect(CALL_STATUS_CONFIG.failed.variant).toBe("destructive");
    expect(CALL_STATUS_CONFIG.error.variant).toBe("destructive");
  });

  it("completed uses secondary variant", () => {
    expect(CALL_STATUS_CONFIG.completed.variant).toBe("secondary");
  });

  it("in_progress uses default variant", () => {
    expect(CALL_STATUS_CONFIG.in_progress.variant).toBe("default");
  });
});

// ---------------------------------------------------------------------------
// CAMPAIGN_STATUS_CONFIG
// ---------------------------------------------------------------------------

describe("CAMPAIGN_STATUS_CONFIG", () => {
  it.each(["draft", "running", "paused", "completed", "cancelled"])(
    "has campaign status '%s'",
    (status) => {
      expect(CAMPAIGN_STATUS_CONFIG).toHaveProperty(status);
    }
  );

  it("each status has label, variant, className, icon", () => {
    for (const config of Object.values(CAMPAIGN_STATUS_CONFIG)) {
      expect(config).toHaveProperty("label");
      expect(config).toHaveProperty("variant");
      expect(config).toHaveProperty("className");
      expect(config).toHaveProperty("icon");
      expect(typeof config.label).toBe("string");
    }
  });

  it("cancelled uses destructive variant", () => {
    expect(CAMPAIGN_STATUS_CONFIG.cancelled.variant).toBe("destructive");
  });
});

// ---------------------------------------------------------------------------
// LEAD_STATUS_COLORS
// ---------------------------------------------------------------------------

describe("LEAD_STATUS_COLORS", () => {
  it("has new, contacted, qualified, unqualified", () => {
    expect(LEAD_STATUS_COLORS).toHaveProperty("new");
    expect(LEAD_STATUS_COLORS).toHaveProperty("contacted");
    expect(LEAD_STATUS_COLORS).toHaveProperty("qualified");
    expect(LEAD_STATUS_COLORS).toHaveProperty("unqualified");
  });

  it("all values are non-empty strings", () => {
    for (const color of Object.values(LEAD_STATUS_COLORS)) {
      expect(typeof color).toBe("string");
      expect(color.length).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// LEAD_QUALIFICATION_COLORS
// ---------------------------------------------------------------------------

describe("LEAD_QUALIFICATION_COLORS", () => {
  it.each(["hot", "warm", "cold", "high", "medium", "low"])(
    "has qualification level '%s'",
    (level) => {
      expect(LEAD_QUALIFICATION_COLORS).toHaveProperty(level);
    }
  );
});

// ---------------------------------------------------------------------------
// INTEREST_CONFIG
// ---------------------------------------------------------------------------

describe("INTEREST_CONFIG", () => {
  it("has high, medium, low", () => {
    expect(INTEREST_CONFIG).toHaveProperty("high");
    expect(INTEREST_CONFIG).toHaveProperty("medium");
    expect(INTEREST_CONFIG).toHaveProperty("low");
  });

  it("each level has color and label", () => {
    for (const config of Object.values(INTEREST_CONFIG)) {
      expect(config).toHaveProperty("color");
      expect(config).toHaveProperty("label");
      expect(typeof config.label).toBe("string");
    }
  });

  it("labels match expected capitalization", () => {
    expect(INTEREST_CONFIG.high.label).toBe("High");
    expect(INTEREST_CONFIG.medium.label).toBe("Medium");
    expect(INTEREST_CONFIG.low.label).toBe("Low");
  });
});

// ---------------------------------------------------------------------------
// SEVERITY_COLORS
// ---------------------------------------------------------------------------

describe("SEVERITY_COLORS", () => {
  it.each(["critical", "high", "medium", "low"])(
    "has severity level '%s'",
    (level) => {
      expect(SEVERITY_COLORS).toHaveProperty(level);
    }
  );

  it("all values contain color classes", () => {
    for (const color of Object.values(SEVERITY_COLORS)) {
      expect(color).toMatch(/bg-/);
      expect(color).toMatch(/text-/);
      expect(color).toMatch(/border-/);
    }
  });
});
