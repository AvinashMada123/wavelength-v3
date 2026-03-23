import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, userEvent } from "@/test/test-utils";
import { renderWithProviders } from "@/test/test-utils";
import { fireEvent } from "@testing-library/react";

// Stable push mock shared between component and test
const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

// Mock command UI components so cmdk doesn't need jsdom compat
vi.mock("@/components/ui/command", () => ({
  CommandDialog: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? <div role="dialog">{children}</div> : null,
  CommandEmpty: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  CommandGroup: ({
    heading,
    children,
  }: {
    heading: string;
    children: React.ReactNode;
  }) => (
    <div>
      <h2>{heading}</h2>
      {children}
    </div>
  ),
  CommandInput: (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input {...props} />
  ),
  CommandItem: ({
    children,
    onSelect,
  }: {
    children: React.ReactNode;
    onSelect: () => void;
  }) => (
    <div role="option" onClick={onSelect}>
      {children}
    </div>
  ),
  CommandList: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  CommandSeparator: () => <hr />,
  CommandShortcut: ({ children }: { children: React.ReactNode }) => (
    <kbd>{children}</kbd>
  ),
}));

// Must import after mocks are set up
import { CommandPalette } from "@/components/command-palette";

function openPalette() {
  fireEvent.keyDown(document, { key: "k", ctrlKey: true });
}

describe("CommandPalette", () => {
  beforeEach(() => {
    pushMock.mockClear();
  });

  it("is not visible initially", () => {
    renderWithProviders(<CommandPalette />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens on Ctrl+K keydown", () => {
    renderWithProviders(<CommandPalette />);
    openPalette();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows navigation items when open", () => {
    renderWithProviders(<CommandPalette />);
    openPalette();

    const navLabels = [
      "Dashboard",
      "Bots",
      "Calls",
      "Call Queue",
      "Call Logs",
      "Analytics",
      "Leads",
      "Campaigns",
      "Team",
      "Settings",
      "Billing",
    ];
    for (const label of navLabels) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("shows quick actions when open", () => {
    renderWithProviders(<CommandPalette />);
    openPalette();

    expect(screen.getByText("New Bot")).toBeInTheDocument();
    expect(screen.getByText("Trigger Call")).toBeInTheDocument();
    expect(screen.getByText("Add Lead")).toBeInTheDocument();
    expect(screen.getByText("New Campaign")).toBeInTheDocument();
  });

  it("calls router.push with correct href when clicking an item", async () => {
    renderWithProviders(<CommandPalette />);
    openPalette();

    // Click "Analytics" nav item (href: /analytics)
    const user = userEvent.setup();
    await user.click(screen.getByRole("option", { name: /analytics/i }));
    expect(pushMock).toHaveBeenCalledWith("/analytics");
  });
});
