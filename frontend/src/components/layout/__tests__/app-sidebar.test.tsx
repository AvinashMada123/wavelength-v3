import { describe, it, expect, vi } from "vitest";
import { screen, renderWithProviders, userEvent } from "@/test/test-utils";

const mockLogout = vi.fn();
const mockUseAuth = vi.fn();
vi.mock("@/contexts/auth-context", () => ({
  useAuth: (...args: any[]) => mockUseAuth(...args),
}));

function setAuthUser(overrides: Record<string, unknown> = {}) {
  mockUseAuth.mockReturnValue({
    user: {
      id: "u1",
      email: "a@b.com",
      display_name: "Test User",
      role: "client_admin",
      org_id: "o1",
      org_name: "Test Org",
      ...overrides,
    },
    logout: mockLogout,
    isAuthenticated: true,
    isLoading: false,
  });
}

vi.mock("@/hooks/use-keyboard-shortcuts", () => ({
  useKeyboardShortcuts: vi.fn(),
}));

vi.mock("@/components/layout/org-switcher", () => ({
  OrgSwitcher: () => <div data-testid="org-switcher" />,
}));

vi.mock("@/components/ui/sidebar", () => ({
  Sidebar: ({ children }: any) => <div>{children}</div>,
  SidebarContent: ({ children }: any) => <div>{children}</div>,
  SidebarFooter: ({ children }: any) => <div>{children}</div>,
  SidebarGroup: ({ children }: any) => <div>{children}</div>,
  SidebarGroupContent: ({ children }: any) => <div>{children}</div>,
  SidebarMenu: ({ children }: any) => <nav>{children}</nav>,
  SidebarMenuButton: ({ children, ...props }: any) => (
    <div {...props}>{children}</div>
  ),
  SidebarMenuItem: ({ children }: any) => <div>{children}</div>,
  SidebarHeader: ({ children }: any) => <div>{children}</div>,
}));

describe("AppSidebar", () => {
  // Lazy import so mocks are applied before module loads
  async function loadAppSidebar() {
    const mod = await import("@/components/layout/app-sidebar");
    return mod.AppSidebar;
  }

  beforeEach(() => {
    setAuthUser();
  });

  const standardNavItems = [
    "Dashboard",
    "Bots",
    "Calls",
    "Call Queue",
    "Call History",
    "Analytics",
    "Leads",
    "Campaigns",
    "Sequences",
    "Team",
    "Settings",
    "Billing",
  ];

  it("renders all 12 standard nav items", async () => {
    const AppSidebar = await loadAppSidebar();
    renderWithProviders(<AppSidebar />);
    for (const name of standardNavItems) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("does NOT render Admin link for client_admin role", async () => {
    const AppSidebar = await loadAppSidebar();
    renderWithProviders(<AppSidebar />);
    expect(screen.queryByText("Admin")).not.toBeInTheDocument();
  });

  it("renders Admin link when user is super_admin", async () => {
    setAuthUser({ role: "super_admin" });

    const AppSidebar = await loadAppSidebar();
    renderWithProviders(<AppSidebar />);
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });

  it("renders user display name and org name", async () => {
    const AppSidebar = await loadAppSidebar();
    renderWithProviders(<AppSidebar />);
    expect(screen.getByText("Test User")).toBeInTheDocument();
    expect(screen.getByText("Test Org")).toBeInTheDocument();
  });

  it("clicking sign out button calls logout", async () => {
    const user = userEvent.setup();
    const AppSidebar = await loadAppSidebar();
    renderWithProviders(<AppSidebar />);
    const signOutButton = screen.getByTitle("Sign out");
    await user.click(signOutButton);
    expect(mockLogout).toHaveBeenCalled();
  });
});
