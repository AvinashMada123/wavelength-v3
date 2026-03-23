import React from "react";
import { render, screen, waitFor, userEvent } from "@/test/test-utils";
import { AuthProvider, useAuth } from "@/contexts/auth-context";

// ---------------------------------------------------------------------------
// Test helper
// ---------------------------------------------------------------------------

function TestConsumer() {
  const auth = useAuth();
  const [error, setError] = React.useState<string | null>(null);
  return (
    <div>
      <span data-testid="loading">{String(auth.isLoading)}</span>
      <span data-testid="authenticated">{String(auth.isAuthenticated)}</span>
      <span data-testid="user">{auth.user?.display_name ?? "none"}</span>
      <span data-testid="error">{error ?? "none"}</span>
      <button onClick={() => auth.login("test@test.com", "pass").catch((e) => setError(e.message))}>Login</button>
      <button onClick={() => auth.signup("new@test.com", "pass", "New User", "New Org").catch((e) => setError(e.message))}>Signup</button>
      <button onClick={auth.logout}>Logout</button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// jsdom localStorage mock
const store: Record<string, string> = {};
const mockLocalStorage = {
  getItem: vi.fn((key: string) => store[key] ?? null),
  setItem: vi.fn((key: string, value: string) => {
    store[key] = value;
  }),
  removeItem: vi.fn((key: string) => {
    delete store[key];
  }),
  clear: vi.fn(() => {
    for (const key of Object.keys(store)) delete store[key];
  }),
  key: vi.fn(),
  length: 0,
};
vi.stubGlobal("localStorage", mockLocalStorage);

const mockUser = {
  id: "u1",
  email: "test@test.com",
  display_name: "Test User",
  role: "client_admin",
  org_id: "org-1",
  org_name: "Test Org",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AuthProvider + useAuth", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of Object.keys(store)) delete store[key];
  });

  it("settles to unauthenticated when no token in localStorage", async () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    // After init settles (no token -> isLoading=false immediately)
    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });
    expect(screen.getByTestId("authenticated")).toHaveTextContent("false");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    // No fetch calls since there was no token
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("login calls fetch, stores tokens, and updates user", async () => {
    // No token in store, so init completes without fetching
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });

    // Setup fetch response for login
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        access_token: "tok-access",
        refresh_token: "tok-refresh",
        user: mockUser,
      }),
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Login" }));

    await waitFor(() => {
      expect(screen.getByTestId("authenticated")).toHaveTextContent("true");
    });

    expect(screen.getByTestId("user")).toHaveTextContent("Test User");
    expect(store["access_token"]).toBe("tok-access");
    expect(store["refresh_token"]).toBe("tok-refresh");

    // Verify fetch was called with correct args
    const loginCall = mockFetch.mock.calls.find(
      (c: any[]) => c[0] === "/api/auth/login",
    );
    expect(loginCall).toBeDefined();
    expect(JSON.parse(loginCall![1].body)).toEqual({
      email: "test@test.com",
      password: "pass",
    });
  });

  it("logout clears localStorage and sets user to null", async () => {
    // Pre-populate localStorage so init fetches /me
    store["access_token"] = "tok";
    store["refresh_token"] = "rtok";
    store["auth_user"] = JSON.stringify(mockUser);

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockUser,
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("authenticated")).toHaveTextContent("true");
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Logout" }));

    expect(screen.getByTestId("authenticated")).toHaveTextContent("false");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(store["access_token"]).toBeUndefined();
    expect(store["refresh_token"]).toBeUndefined();
    expect(store["auth_user"]).toBeUndefined();
  });

  it("login failure throws with detail message", async () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });

    mockFetch.mockResolvedValueOnce({
      ok: false,
      text: async () => JSON.stringify({ detail: "Invalid credentials" }),
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Login" }));

    await waitFor(() => {
      expect(screen.getByTestId("error")).toHaveTextContent("Invalid credentials");
    });
  });

  it("signup calls fetch, stores tokens, and updates user", async () => {
    const signupUser = {
      ...mockUser,
      email: "new@test.com",
      display_name: "New User",
      org_name: "New Org",
    };

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        access_token: "tok-signup-access",
        refresh_token: "tok-signup-refresh",
        user: signupUser,
      }),
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Signup" }));

    await waitFor(() => {
      expect(screen.getByTestId("authenticated")).toHaveTextContent("true");
    });

    expect(screen.getByTestId("user")).toHaveTextContent("New User");
    expect(store["access_token"]).toBe("tok-signup-access");
    expect(store["refresh_token"]).toBe("tok-signup-refresh");

    const signupCall = mockFetch.mock.calls.find(
      (c: any[]) => c[0] === "/api/auth/signup",
    );
    expect(signupCall).toBeDefined();
    expect(JSON.parse(signupCall![1].body)).toEqual({
      email: "new@test.com",
      password: "pass",
      display_name: "New User",
      org_name: "New Org",
    });
  });

  it("refreshes token when /me returns unauthorized", async () => {
    store["access_token"] = "expired-tok";
    store["refresh_token"] = "valid-refresh";

    // First call: /me with expired token → 401
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
    });

    // Second call: /auth/refresh → new access token
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ access_token: "new-tok" }),
    });

    // Third call: /me with new token → success
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockUser,
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("authenticated")).toHaveTextContent("true");
    });

    expect(screen.getByTestId("user")).toHaveTextContent("Test User");
    expect(store["access_token"]).toBe("new-tok");
  });

  it("falls back to cached user on network error", async () => {
    store["access_token"] = "some-tok";
    store["auth_user"] = JSON.stringify(mockUser);

    mockFetch.mockRejectedValueOnce(new Error("Network error"));

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });

    expect(screen.getByTestId("user")).toHaveTextContent("Test User");
    expect(screen.getByTestId("authenticated")).toHaveTextContent("true");
  });

  it("throws when useAuth is used outside AuthProvider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => render(<TestConsumer />)).toThrow(
      "useAuth must be used within an AuthProvider",
    );

    spy.mockRestore();
  });
});
