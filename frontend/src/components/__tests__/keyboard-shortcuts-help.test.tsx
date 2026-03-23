import { describe, it, expect, vi } from "vitest";
import { screen } from "@/test/test-utils";
import { renderWithProviders } from "@/test/test-utils";
import { fireEvent } from "@testing-library/react";

// Mock Dialog so we don't need Radix DOM internals
vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({
    open,
    children,
  }: {
    open: boolean;
    onOpenChange: (v: boolean) => void;
    children: React.ReactNode;
  }) => (open ? <div role="dialog">{children}</div> : null),
  DialogContent: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DialogHeader: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DialogTitle: ({ children }: { children: React.ReactNode }) => (
    <h2>{children}</h2>
  ),
  DialogDescription: ({ children }: { children: React.ReactNode }) => (
    <p>{children}</p>
  ),
}));

import { KeyboardShortcutsHelp } from "@/components/keyboard-shortcuts-help";

function pressQuestion(opts: Partial<KeyboardEventInit> = {}) {
  fireEvent.keyDown(document, { key: "?", ...opts });
}

describe("KeyboardShortcutsHelp", () => {
  it("is not visible initially", () => {
    renderWithProviders(<KeyboardShortcutsHelp />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it('opens on "?" keypress', () => {
    renderWithProviders(<KeyboardShortcutsHelp />);
    pressQuestion();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it('shows "Keyboard Shortcuts" title', () => {
    renderWithProviders(<KeyboardShortcutsHelp />);
    pressQuestion();
    expect(
      screen.getByRole("heading", { name: "Keyboard Shortcuts" })
    ).toBeInTheDocument();
  });

  it("shows all 6 shortcut descriptions", () => {
    renderWithProviders(<KeyboardShortcutsHelp />);
    pressQuestion();

    const descriptions = [
      "Go to Dashboard",
      "Go to Bots",
      "Go to Call Logs",
      "Go to Analytics",
      "Open command palette",
      "Show this help",
    ];
    for (const desc of descriptions) {
      expect(screen.getByText(desc)).toBeInTheDocument();
    }
  });

  it('does not open when "?" is pressed with metaKey', () => {
    renderWithProviders(<KeyboardShortcutsHelp />);
    pressQuestion({ metaKey: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
