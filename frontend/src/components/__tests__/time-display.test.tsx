import { describe, it, expect, vi } from "vitest";
import { screen } from "@/test/test-utils";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("@/lib/utils", async () => {
  const actual = await vi.importActual("@/lib/utils");
  return {
    ...actual,
    timeAgo: vi.fn(() => "2 hours ago"),
    formatDate: vi.fn(() => "March 20, 2026 10:00 AM"),
  };
});

import { TimeDisplay } from "@/components/time-display";

describe("TimeDisplay", () => {
  it('shows "--" when date is empty string', () => {
    renderWithProviders(<TimeDisplay date="" />);
    expect(screen.getByText("--")).toBeInTheDocument();
  });

  it("shows relative time text from timeAgo", () => {
    renderWithProviders(<TimeDisplay date="2026-03-20T10:00:00Z" />);
    expect(screen.getByText("2 hours ago")).toBeInTheDocument();
  });

  it("applies className", () => {
    const { container } = renderWithProviders(
      <TimeDisplay date="" className="text-muted" />
    );
    const span = screen.getByText("--");
    expect(span).toHaveClass("text-muted");
  });
});
