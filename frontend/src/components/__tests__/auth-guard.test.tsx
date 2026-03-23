import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@/test/test-utils";
import { renderWithProviders } from "@/test/test-utils";

const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: mockReplace,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

const mockUseAuth = vi.fn();

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => mockUseAuth(),
}));

import { AuthGuard } from "@/components/auth-guard";

describe("AuthGuard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading screen when isLoading", () => {
    mockUseAuth.mockReturnValue({ isLoading: true, isAuthenticated: false });

    renderWithProviders(
      <AuthGuard>
        <div>Protected content</div>
      </AuthGuard>
    );

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("redirects to /login when not authenticated", () => {
    mockUseAuth.mockReturnValue({ isLoading: false, isAuthenticated: false });

    renderWithProviders(
      <AuthGuard>
        <div>Protected content</div>
      </AuthGuard>
    );

    expect(mockReplace).toHaveBeenCalledWith("/login");
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("renders children when authenticated", () => {
    mockUseAuth.mockReturnValue({ isLoading: false, isAuthenticated: true });

    renderWithProviders(
      <AuthGuard>
        <div>Protected content</div>
      </AuthGuard>
    );

    expect(screen.getByText("Protected content")).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("does not redirect when loading even if not authenticated", () => {
    mockUseAuth.mockReturnValue({ isLoading: true, isAuthenticated: false });

    renderWithProviders(
      <AuthGuard>
        <div>Protected content</div>
      </AuthGuard>
    );

    expect(mockReplace).not.toHaveBeenCalled();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });
});
