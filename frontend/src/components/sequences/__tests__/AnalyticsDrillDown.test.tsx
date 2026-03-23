import { screen, renderWithProviders, userEvent } from "@/test/test-utils";
import { AnalyticsDrillDown } from "../AnalyticsDrillDown";
import type { FunnelData, FailuresData, LeadDetail } from "@/lib/sequences-api";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const mockFunnelData: FunnelData = {
  template_name: "Onboarding Flow",
  total_entered: 250,
  steps: [
    { step_order: 1, name: "Welcome", sent: 240, skipped: 5, failed: 5, replied: 80, drop_off_rate: 0 },
    { step_order: 2, name: "Follow Up", sent: 200, skipped: 10, failed: 30, replied: 50, drop_off_rate: 0.17 },
  ],
};

const mockFailuresData: FailuresData = {
  total_failed: 35,
  reasons: [
    { reason: "Invalid phone", count: 20 },
    { reason: "Rate limited", count: 15 },
  ],
  retry_stats: { total_retried: 10, retry_success_rate: 0.6 },
};

const mockLeadDetail: LeadDetail = {
  lead_id: "lead-1",
  lead_name: "Jane Doe",
  score: 82,
  tier: "hot",
  score_breakdown: {
    activity: { score: 30, max: 40 },
    recency: { score: 25, max: 30 },
    outcome: { score: 27, max: 30 },
  },
  active_sequences: 3,
  total_replies: 12,
  avg_reply_time_hours: 4.5,
  timeline: [
    {
      timestamp: "2026-03-10T09:00:00Z",
      template_name: "Onboarding",
      step_name: "Welcome",
      channel: "whatsapp_template",
      status: "sent",
      content_preview: "Hi Jane!",
      reply_text: null,
    },
  ],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AnalyticsDrillDown", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("template mode", () => {
    it("shows back button and template name as title", () => {
      renderWithProviders(
        <AnalyticsDrillDown
          type="template"
          onBack={vi.fn()}
          funnelData={mockFunnelData}
          failuresData={mockFailuresData}
        />,
      );

      expect(screen.getByRole("button", { name: /back/i })).toBeInTheDocument();
      expect(screen.getByText("Onboarding Flow")).toBeInTheDocument();
    });

    it("shows Total Entered KPI and Step Funnel section", () => {
      renderWithProviders(
        <AnalyticsDrillDown
          type="template"
          onBack={vi.fn()}
          funnelData={mockFunnelData}
          failuresData={null}
        />,
      );

      expect(screen.getByText("Total Entered")).toBeInTheDocument();
      expect(screen.getByText(mockFunnelData.total_entered.toLocaleString())).toBeInTheDocument();
      expect(screen.getByText("Step Funnel")).toBeInTheDocument();
    });

    it("shows funnel steps with names and sent counts", () => {
      renderWithProviders(
        <AnalyticsDrillDown
          type="template"
          onBack={vi.fn()}
          funnelData={mockFunnelData}
          failuresData={null}
        />,
      );

      expect(screen.getByText(/1\. Welcome/)).toBeInTheDocument();
      expect(screen.getByText(/240 sent/)).toBeInTheDocument();
      expect(screen.getByText(/2\. Follow Up/)).toBeInTheDocument();
      expect(screen.getByText(/200 sent/)).toBeInTheDocument();
    });
  });

  describe("lead mode", () => {
    it("shows lead name as title and tier badge", () => {
      renderWithProviders(
        <AnalyticsDrillDown
          type="lead"
          onBack={vi.fn()}
          leadDetail={mockLeadDetail}
        />,
      );

      expect(screen.getByText(mockLeadDetail.lead_name!)).toBeInTheDocument();
      expect(screen.getByText("Hot")).toBeInTheDocument();
    });

    it("shows Score Breakdown with Activity, Recency, and Outcome", () => {
      renderWithProviders(
        <AnalyticsDrillDown
          type="lead"
          onBack={vi.fn()}
          leadDetail={mockLeadDetail}
        />,
      );

      expect(screen.getByText("Score Breakdown")).toBeInTheDocument();
      expect(screen.getByText("Activity")).toBeInTheDocument();
      const { activity, recency, outcome } = mockLeadDetail.score_breakdown;
      expect(screen.getByText(`${activity.score}/${activity.max}`)).toBeInTheDocument();
      expect(screen.getByText("Recency")).toBeInTheDocument();
      expect(screen.getByText(`${recency.score}/${recency.max}`)).toBeInTheDocument();
      expect(screen.getByText("Outcome")).toBeInTheDocument();
      expect(screen.getByText(`${outcome.score}/${outcome.max}`)).toBeInTheDocument();
    });

    it("shows quick stats (Active Sequences, Total Replies, Avg Reply Time)", () => {
      renderWithProviders(
        <AnalyticsDrillDown
          type="lead"
          onBack={vi.fn()}
          leadDetail={mockLeadDetail}
        />,
      );

      expect(screen.getByText("Active Sequences")).toBeInTheDocument();
      expect(screen.getByText(String(mockLeadDetail.active_sequences))).toBeInTheDocument();
      expect(screen.getByText("Total Replies")).toBeInTheDocument();
      expect(screen.getByText(String(mockLeadDetail.total_replies))).toBeInTheDocument();
      expect(screen.getByText("Avg Reply Time")).toBeInTheDocument();
      expect(screen.getByText(`${mockLeadDetail.avg_reply_time_hours}h`)).toBeInTheDocument();
    });
  });

  it("back button calls onBack", async () => {
    const onBack = vi.fn();
    renderWithProviders(
      <AnalyticsDrillDown
        type="template"
        onBack={onBack}
        funnelData={mockFunnelData}
        failuresData={null}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /back/i }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
