import { describe, it, expect, vi } from "vitest";
import { screen } from "@/test/test-utils";
import { renderWithProviders, userEvent } from "@/test/test-utils";
import {
  DateRangePicker,
  type DateRange,
} from "@/components/date-range-picker";

// Radix Popover needs pointer events; mock Popover for reliable jsdom testing
vi.mock("@/components/ui/popover", () => ({
  Popover: ({
    open,
    onOpenChange,
    children,
  }: {
    open: boolean;
    onOpenChange: (v: boolean) => void;
    children: React.ReactNode;
  }) => (
    <div data-testid="popover" data-open={open} onClick={() => onOpenChange(!open)}>
      {children}
    </div>
  ),
  PopoverTrigger: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  PopoverContent: ({
    children,
    ...rest
  }: {
    children: React.ReactNode;
    [k: string]: unknown;
  }) => <div {...rest}>{children}</div>,
}));

const emptyRange: DateRange = { from: null, to: null };

describe("DateRangePicker", () => {
  it('renders trigger button with "Select dates" when no value', () => {
    renderWithProviders(
      <DateRangePicker value={emptyRange} onChange={vi.fn()} />
    );

    expect(
      screen.getByRole("button", { name: /select dates/i })
    ).toBeInTheDocument();
  });

  it("opens popover on click showing preset buttons", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <DateRangePicker value={emptyRange} onChange={vi.fn()} />
    );

    await user.click(screen.getByRole("button", { name: /select dates/i }));

    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Last 7 days")).toBeInTheDocument();
    expect(screen.getByText("Last 30 days")).toBeInTheDocument();
    expect(screen.getByText("Last 90 days")).toBeInTheDocument();
  });

  it("calls onChange with date range when clicking a preset", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    renderWithProviders(
      <DateRangePicker value={emptyRange} onChange={onChange} />
    );

    await user.click(screen.getByRole("button", { name: /select dates/i }));
    await user.click(screen.getByText("Today"));

    expect(onChange).toHaveBeenCalledOnce();
    const range = onChange.mock.calls[0][0] as DateRange;
    expect(range.from).toBeTruthy();
    expect(range.to).toBeTruthy();
  });

  it('shows "Custom Range" button', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <DateRangePicker value={emptyRange} onChange={vi.fn()} />
    );

    await user.click(screen.getByRole("button", { name: /select dates/i }));
    expect(screen.getByText("Custom Range")).toBeInTheDocument();
  });

  it("shows date inputs when Custom Range is clicked", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <DateRangePicker value={emptyRange} onChange={vi.fn()} />
    );

    await user.click(screen.getByRole("button", { name: /select dates/i }));
    await user.click(screen.getByText("Custom Range"));

    expect(screen.getByText("From")).toBeInTheDocument();
    expect(screen.getByText("To")).toBeInTheDocument();
  });

  it("Apply button is disabled when no dates selected", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <DateRangePicker value={emptyRange} onChange={vi.fn()} />
    );

    await user.click(screen.getByRole("button", { name: /select dates/i }));
    await user.click(screen.getByText("Custom Range"));

    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
  });

  it("shows time inputs when enableTime is true", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <DateRangePicker value={emptyRange} onChange={vi.fn()} enableTime />
    );
    await user.click(screen.getByRole("button", { name: /select dates/i }));
    await user.click(screen.getByText("Custom Range"));

    const timeInputs = document.querySelectorAll('input[type="time"]');
    expect(timeInputs.length).toBe(2); // From time + To time
  });

  it("shows preset label when value matches a preset", () => {
    const today = new Date().toISOString().slice(0, 10);
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    const range: DateRange = {
      from: todayStart.toISOString().slice(0, 10),
      to: today,
    };
    renderWithProviders(
      <DateRangePicker value={range} onChange={vi.fn()} />
    );
    // The trigger button (with the calendar icon) should show "Today" as its label
    const buttons = screen.getAllByRole("button", { name: /today/i });
    // At least one button (the trigger) displays the preset label
    expect(buttons.length).toBeGreaterThanOrEqual(1);
    // The trigger button has data-slot="button" (shadcn Button)
    const trigger = buttons.find((b) => b.getAttribute("data-slot") === "button");
    expect(trigger).toBeDefined();
    expect(trigger!.textContent).toContain("Today");
  });
});
