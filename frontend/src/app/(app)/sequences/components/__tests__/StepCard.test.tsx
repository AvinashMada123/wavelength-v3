import { screen, renderWithProviders, userEvent, fireEvent } from "@/test/test-utils";
import { StepCard } from "../StepCard";
import type { SequenceStep } from "@/lib/sequences-api";

vi.mock("@/lib/sequences-api", () => ({
  testStep: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Default mock data
// ---------------------------------------------------------------------------

const mockStep: SequenceStep = {
  id: "step-1",
  template_id: "t1",
  step_order: 1,
  name: "Follow Up",
  is_active: true,
  channel: "whatsapp_template",
  timing_type: "delay",
  timing_value: { days: 1, hours: 2 },
  skip_conditions: null,
  content_type: "static_template",
  whatsapp_template_name: "welcome_msg",
  whatsapp_template_params: ["John"],
  ai_prompt: null,
  ai_model: null,
  voice_bot_id: null,
  expects_reply: false,
  reply_handler: null,
};

const defaultProps = {
  step: mockStep,
  bots: [{ id: "bot-1", name: "Sales Bot" }],
  variables: [],
  onUpdate: vi.fn(),
  onDelete: vi.fn(),
  onTestPrompt: vi.fn(),
  onAddVariable: vi.fn(),
  isExpanded: false,
  onToggleExpand: vi.fn(),
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StepCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("collapsed view", () => {
    it("shows step name, step order, and channel badge", () => {
      renderWithProviders(<StepCard {...defaultProps} />);

      expect(screen.getByText("Follow Up")).toBeInTheDocument();
      expect(screen.getByText("1")).toBeInTheDocument();
      expect(screen.getByText("WhatsApp Template")).toBeInTheDocument();
    });

    it("calls onToggleExpand when card is clicked", async () => {
      renderWithProviders(<StepCard {...defaultProps} />);

      const user = userEvent.setup();
      await user.click(screen.getByText("Follow Up"));

      expect(defaultProps.onToggleExpand).toHaveBeenCalledTimes(1);
    });

    it("shows Inactive badge when step is not active", () => {
      const inactiveStep = { ...mockStep, is_active: false };
      renderWithProviders(
        <StepCard {...defaultProps} step={inactiveStep} />,
      );

      expect(screen.getByText("Inactive")).toBeInTheDocument();
    });
  });

  describe("expanded view", () => {
    it("shows Step Name input, Channel select, and Content Type select", () => {
      renderWithProviders(
        <StepCard {...defaultProps} isExpanded={true} />,
      );

      expect(screen.getByText("Step Name")).toBeInTheDocument();
      expect(screen.getByText("Channel")).toBeInTheDocument();
      expect(screen.getByText("Content Type")).toBeInTheDocument();
      expect(screen.getByDisplayValue("Follow Up")).toBeInTheDocument();
    });

    it("shows delete button and clicking calls onDelete", async () => {
      renderWithProviders(
        <StepCard {...defaultProps} isExpanded={true} />,
      );

      const deleteBtn = screen.getByRole("button", { name: /delete step/i });
      expect(deleteBtn).toBeInTheDocument();

      const user = userEvent.setup();
      await user.click(deleteBtn);

      expect(defaultProps.onDelete).toHaveBeenCalledWith("step-1");
    });

    it("shows AI prompt textarea and Test Prompt button for ai_generated content type", () => {
      const aiStep: SequenceStep = {
        ...mockStep,
        content_type: "ai_generated",
        ai_prompt: "Hello {{name}}",
        ai_model: "claude-sonnet",
      };
      renderWithProviders(
        <StepCard {...defaultProps} step={aiStep} isExpanded={true} />,
      );

      // The prompt textarea should contain the ai_prompt value
      expect(screen.getByDisplayValue("Hello {{name}}")).toBeInTheDocument();
      // Test Prompt button should be visible
      expect(screen.getByRole("button", { name: /test prompt/i })).toBeInTheDocument();
    });

    it("shows Voice Bot label for voice_call content type", () => {
      const voiceStep: SequenceStep = {
        ...mockStep,
        content_type: "voice_call",
        voice_bot_id: "bot-1",
      };
      renderWithProviders(
        <StepCard
          {...defaultProps}
          step={voiceStep}
          bots={[{ id: "bot-1", name: "Sales Bot" }]}
          isExpanded={true}
        />,
      );

      // The Voice Bot label should be present
      expect(screen.getByText("Voice Bot")).toBeInTheDocument();
    });

    it("shows Active label and Delete button coexist in footer", () => {
      renderWithProviders(
        <StepCard {...defaultProps} isExpanded={true} />,
      );

      expect(screen.getByText("Active")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /delete step/i })).toBeInTheDocument();
    });

    it("name input triggers onUpdate on blur", () => {
      vi.useFakeTimers();
      const onUpdate = vi.fn();
      renderWithProviders(
        <StepCard {...defaultProps} onUpdate={onUpdate} isExpanded={true} />,
      );

      const nameInput = screen.getByDisplayValue("Follow Up");
      fireEvent.change(nameInput, { target: { value: "New Name" } });
      fireEvent.blur(nameInput);

      expect(onUpdate).toHaveBeenCalledWith("step-1", expect.objectContaining({ name: "New Name" }));
      vi.useRealTimers();
    });
  });
});
