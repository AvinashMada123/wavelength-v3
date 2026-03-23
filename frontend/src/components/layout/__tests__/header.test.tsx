import { describe, it, expect, vi } from "vitest";
import { screen, renderWithProviders, userEvent } from "@/test/test-utils";
import { Header } from "@/components/layout/header";

let currentTheme = "light";
const mockSetTheme = vi.fn();
vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: currentTheme, setTheme: mockSetTheme }),
}));

vi.mock("@/components/ui/sidebar", () => ({
  SidebarTrigger: () => <button>sidebar</button>,
}));

describe("Header", () => {
  it("renders title text", () => {
    renderWithProviders(<Header title="Dashboard" />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("renders toggle theme button", () => {
    renderWithProviders(<Header title="Dashboard" />);
    expect(
      screen.getByRole("button", { name: /toggle theme/i })
    ).toBeInTheDocument();
  });

  it("clicking toggle calls setTheme", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Header title="Dashboard" />);
    const button = screen.getByRole("button", { name: /toggle theme/i });
    await user.click(button);
    expect(mockSetTheme).toHaveBeenCalledWith("dark");
  });

  it("calls setTheme('light') when currently in dark mode", async () => {
    currentTheme = "dark";
    const user = userEvent.setup();
    renderWithProviders(<Header title="Test" />);
    await user.click(screen.getByRole("button", { name: /toggle theme/i }));
    expect(mockSetTheme).toHaveBeenCalledWith("light");
    currentTheme = "light"; // reset for other tests
  });
});
