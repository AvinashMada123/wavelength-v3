import { describe, it, expect, vi } from "vitest";
import { screen, renderWithProviders, waitFor } from "@/test/test-utils";
import { fetchUserOrgs } from "@/lib/api";

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      org_id: "org-1",
      org_name: "Org A",
      role: "client_admin",
    },
    switchOrg: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({
  fetchUserOrgs: vi.fn(),
}));

describe("OrgSwitcher", () => {
  async function loadOrgSwitcher() {
    const mod = await import("@/components/layout/org-switcher");
    return mod.OrgSwitcher;
  }

  it("returns null when user has 1 org and is not super_admin", async () => {
    vi.mocked(fetchUserOrgs).mockResolvedValue([
      {
        org_id: "org-1",
        org_name: "Org A",
        role: "client_admin",
        is_active: true,
        org_slug: "org-a",
      },
    ]);

    const OrgSwitcher = await loadOrgSwitcher();
    const { container } = renderWithProviders(<OrgSwitcher />);

    // Wait for the useEffect to fire and orgs to load
    await waitFor(() => {
      expect(fetchUserOrgs).toHaveBeenCalled();
    });

    // Component should render nothing since only 1 org and not super_admin
    expect(container.innerHTML).toBe("");
  });

  it("shows switcher when user has multiple orgs", async () => {
    vi.mocked(fetchUserOrgs).mockResolvedValue([
      {
        org_id: "org-1",
        org_name: "Org A",
        role: "client_admin",
        is_active: true,
        org_slug: "org-a",
      },
      {
        org_id: "org-2",
        org_name: "Org B",
        role: "client_admin",
        is_active: false,
        org_slug: "org-b",
      },
    ]);

    const OrgSwitcher = await loadOrgSwitcher();
    renderWithProviders(<OrgSwitcher />);

    await waitFor(() => {
      expect(screen.getByText("Org A")).toBeInTheDocument();
    });
  });

  it("does not render when fetchUserOrgs fails", async () => {
    vi.mocked(fetchUserOrgs).mockRejectedValue(new Error("Network error"));
    const OrgSwitcher = await loadOrgSwitcher();
    const { container } = renderWithProviders(<OrgSwitcher />);
    await waitFor(() => {
      expect(fetchUserOrgs).toHaveBeenCalled();
    });
    // Silent failure — component renders nothing since orgs is empty and user is not super_admin
    expect(container.innerHTML).toBe("");
  });
});
