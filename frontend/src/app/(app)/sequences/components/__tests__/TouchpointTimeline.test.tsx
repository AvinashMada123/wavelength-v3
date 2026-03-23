import { screen, renderWithProviders, userEvent, waitFor } from "@/test/test-utils";
import { toast } from "sonner";
import { TouchpointTimeline } from "../TouchpointTimeline";
import type { SequenceTouchpoint } from "@/lib/sequences-api";

const mockRetryTouchpoint = vi.fn();

vi.mock("@/lib/sequences-api", () => ({
  retryTouchpoint: (...args: any[]) => mockRetryTouchpoint(...args),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeTouchpoint(overrides: Partial<SequenceTouchpoint> = {}): SequenceTouchpoint {
  return {
    id: "tp-1",
    instance_id: "inst-1",
    step_order: 1,
    step_snapshot: { name: "Welcome Message", channel: "whatsapp_template" },
    status: "sent",
    scheduled_at: "2026-03-15T10:00:00Z",
    generated_content: null,
    sent_at: "2026-03-15T10:01:00Z",
    reply_text: null,
    reply_response: null,
    error_message: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TouchpointTimeline", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows empty state when no touchpoints", () => {
    renderWithProviders(<TouchpointTimeline touchpoints={[]} />);

    expect(screen.getByText("No touchpoints yet.")).toBeInTheDocument();
  });

  it("renders touchpoint with step name from snapshot", () => {
    renderWithProviders(
      <TouchpointTimeline touchpoints={[makeTouchpoint()]} />,
    );

    expect(screen.getByText("Welcome Message")).toBeInTheDocument();
  });

  it("shows status badge", () => {
    renderWithProviders(
      <TouchpointTimeline
        touchpoints={[
          makeTouchpoint({ status: "sent" }),
          makeTouchpoint({ id: "tp-2", step_order: 2, status: "pending", step_snapshot: { name: "Follow Up" } }),
        ]}
      />,
    );

    expect(screen.getByText("Sent")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("shows Retry button for failed touchpoint", () => {
    renderWithProviders(
      <TouchpointTimeline
        touchpoints={[
          makeTouchpoint({
            status: "failed",
            error_message: "Delivery failed",
          }),
        ]}
      />,
    );

    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Delivery failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("clicking Retry calls retryTouchpoint API", async () => {
    mockRetryTouchpoint.mockResolvedValueOnce({ success: true });

    renderWithProviders(
      <TouchpointTimeline
        touchpoints={[
          makeTouchpoint({
            status: "failed",
            error_message: "Delivery failed",
          }),
        ]}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(mockRetryTouchpoint).toHaveBeenCalledWith("tp-1");
    });
  });

  it("retry failure shows toast.error", async () => {
    mockRetryTouchpoint.mockRejectedValueOnce(new Error("Server error"));

    renderWithProviders(
      <TouchpointTimeline
        touchpoints={[
          makeTouchpoint({
            status: "failed",
            error_message: "Delivery failed",
          }),
        ]}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Failed to retry touchpoint");
    });
  });

  it("sent touchpoint shows generated content", () => {
    renderWithProviders(
      <TouchpointTimeline
        touchpoints={[
          makeTouchpoint({
            status: "sent",
            generated_content: "Hello! Welcome aboard.",
          }),
        ]}
      />,
    );

    expect(screen.getByText("Hello! Welcome aboard.")).toBeInTheDocument();
  });

  it("replied touchpoint shows reply text", () => {
    renderWithProviders(
      <TouchpointTimeline
        touchpoints={[
          makeTouchpoint({
            status: "replied",
            reply_text: "Thanks for reaching out",
          }),
        ]}
      />,
    );

    expect(screen.getByText("Thanks for reaching out")).toBeInTheDocument();
  });
});
