import { screen, renderWithProviders, userEvent, waitFor } from "@/test/test-utils";
import { toast } from "sonner";
import { PromptTestPanel } from "../PromptTestPanel";

const mockTestPrompt = vi.fn();

vi.mock("@/lib/sequences-api", () => ({
  testPrompt: (...args: any[]) => mockTestPrompt(...args),
}));

vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: any) => <div>{children}</div>,
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PromptTestPanel", () => {
  const baseProps = {
    isOpen: true,
    onClose: vi.fn(),
    prompt: "Hello {{lead_name}}, your appointment is on {{date}}.",
    model: "claude-sonnet",
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns null when not open", () => {
    const { container } = renderWithProviders(
      <PromptTestPanel {...baseProps} isOpen={false} />,
    );

    expect(container.innerHTML).toBe("");
  });

  it("shows header 'Test Prompt' when open", () => {
    renderWithProviders(<PromptTestPanel {...baseProps} />);

    expect(screen.getByText("Test Prompt")).toBeInTheDocument();
  });

  it("extracts and shows variable inputs from prompt", () => {
    renderWithProviders(<PromptTestPanel {...baseProps} />);

    expect(screen.getByPlaceholderText("Value for lead_name")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Value for date")).toBeInTheDocument();
  });

  it("shows Generate button", () => {
    renderWithProviders(<PromptTestPanel {...baseProps} />);

    expect(screen.getByRole("button", { name: /generate/i })).toBeInTheDocument();
  });

  it("Generate calls testPrompt and shows result", async () => {
    mockTestPrompt.mockResolvedValueOnce({
      generated_content: "Hello John, your appointment is on Monday.",
      tokens_used: 42,
      latency_ms: 150,
      cost_estimate: 0.0012,
      model: "claude-sonnet",
    });

    renderWithProviders(<PromptTestPanel {...baseProps} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() => {
      expect(mockTestPrompt).toHaveBeenCalledWith({
        prompt: baseProps.prompt,
        variables: {},
        model: "claude-sonnet",
      });
    });

    await waitFor(() => {
      expect(
        screen.getByText("Hello John, your appointment is on Monday."),
      ).toBeInTheDocument();
    });

    expect(screen.getByText(/42 tokens/)).toBeInTheDocument();
    expect(screen.getByText(/150ms/)).toBeInTheDocument();
    expect(screen.getByText(/\$0\.0012/)).toBeInTheDocument();
  });

  it("shows toast.error on generate failure", async () => {
    mockTestPrompt.mockRejectedValueOnce(new Error("API error"));

    renderWithProviders(<PromptTestPanel {...baseProps} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("API error");
    });
  });

  it("passes variable values to API", async () => {
    mockTestPrompt.mockResolvedValueOnce({
      generated_content: "Output",
      tokens_used: 10,
      latency_ms: 50,
      cost_estimate: 0.001,
      model: "claude-sonnet",
    });

    renderWithProviders(<PromptTestPanel {...baseProps} />);

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Value for lead_name"), "Alice");
    await user.type(screen.getByPlaceholderText("Value for date"), "Monday");
    await user.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() => {
      expect(mockTestPrompt).toHaveBeenCalledWith({
        prompt: baseProps.prompt,
        variables: { lead_name: "Alice", date: "Monday" },
        model: "claude-sonnet",
      });
    });
  });

  it("close button calls onClose", async () => {
    const onClose = vi.fn();
    renderWithProviders(<PromptTestPanel {...baseProps} onClose={onClose} />);

    const user = userEvent.setup();
    // The close button is the ghost button with X icon in the header
    const buttons = screen.getAllByRole("button");
    // The close button is small (h-7 w-7) — it's the first button in the header area
    const closeBtn = buttons.find((btn) => btn.querySelector("svg") && btn.textContent === "");
    expect(closeBtn).toBeTruthy();
    await user.click(closeBtn!);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows Try Again button after result and re-calls testPrompt", async () => {
    mockTestPrompt.mockResolvedValueOnce({
      generated_content: "First output",
      tokens_used: 10,
      latency_ms: 50,
      cost_estimate: 0.001,
      model: "claude-sonnet",
    });

    renderWithProviders(<PromptTestPanel {...baseProps} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() => {
      expect(screen.getByText("First output")).toBeInTheDocument();
    });

    // Try Again button should now be visible
    const tryAgainBtn = screen.getByRole("button", { name: /try again/i });
    expect(tryAgainBtn).toBeInTheDocument();

    mockTestPrompt.mockResolvedValueOnce({
      generated_content: "Second output",
      tokens_used: 15,
      latency_ms: 60,
      cost_estimate: 0.002,
      model: "claude-sonnet",
    });

    await user.click(tryAgainBtn);

    await waitFor(() => {
      expect(mockTestPrompt).toHaveBeenCalledTimes(2);
    });
  });
});
