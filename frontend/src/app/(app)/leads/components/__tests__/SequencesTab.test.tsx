import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@/test/test-utils";
import { renderWithProviders } from "@/test/test-utils";
import { SequencesTab } from "../SequencesTab";

vi.mock("@/lib/sequences-api", () => ({
  fetchInstances: vi.fn(),
  fetchInstance: vi.fn(),
}));

import { fetchInstances } from "@/lib/sequences-api";

const mockFetchInstances = vi.mocked(fetchInstances);

describe("SequencesTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", () => {
    mockFetchInstances.mockReturnValue(new Promise(() => {}));
    const { container } = renderWithProviders(<SequencesTab leadId="lead-1" />);
    // Component renders 3 Skeleton elements during loading
    const firstChild = container.firstElementChild;
    expect(firstChild).toBeTruthy();
    expect(firstChild!.children.length).toBe(3);
  });

  it("shows error state when fetch fails", async () => {
    mockFetchInstances.mockRejectedValue(new Error("Network error"));
    renderWithProviders(<SequencesTab leadId="lead-1" />);

    await waitFor(() => {
      expect(screen.getByText("Failed to load sequences")).toBeInTheDocument();
    });
  });

  it("shows empty state when no instances", async () => {
    mockFetchInstances.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<SequencesTab leadId="lead-1" />);

    await waitFor(() => {
      expect(
        screen.getByText("No engagement sequences for this lead")
      ).toBeInTheDocument();
    });
  });

  it("renders instance cards when data is available", async () => {
    mockFetchInstances.mockResolvedValue({
      items: [
        {
          id: "inst-1",
          template_id: "t1",
          template_name: "Welcome Sequence",
          lead_id: "lead-1",
          status: "active",
          context_data: {},
          current_step: 2,
          started_at: "2026-03-01T10:00:00Z",
        },
      ],
      total: 1,
    });

    renderWithProviders(<SequencesTab leadId="lead-1" />);

    await waitFor(() => {
      expect(screen.getByText("Welcome Sequence")).toBeInTheDocument();
    });
    expect(screen.getByText("active")).toBeInTheDocument();
  });
});
