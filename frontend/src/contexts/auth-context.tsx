"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: "super_admin" | "client_admin" | "client_user";
  org_id: string;
  org_name: string;
}

interface AuthContextType {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, displayName: string, orgName: string) => Promise<void>;
  logout: () => void;
  acceptInvite: (inviteId: string, password: string, displayName: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function storeAuth(accessToken: string, refreshToken: string, user: AuthUser) {
  localStorage.setItem("access_token", accessToken);
  localStorage.setItem("refresh_token", refreshToken);
  localStorage.setItem("auth_user", JSON.stringify(user));
}

function clearAuth() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("auth_user");
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function init() {
      const token = localStorage.getItem("access_token");
      if (!token) {
        setIsLoading(false);
        return;
      }

      try {
        // Validate token with /api/auth/me
        const res = await fetch("/api/auth/me", {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (res.ok) {
          const data = await res.json();
          setUser(data);
          localStorage.setItem("auth_user", JSON.stringify(data));
        } else {
          // Token invalid — try refresh
          const refreshed = await tryRefresh();
          if (!refreshed) {
            clearAuth();
            setUser(null);
          }
        }
      } catch {
        // Network error — fall back to cached user
        const cached = localStorage.getItem("auth_user");
        if (cached) {
          try {
            setUser(JSON.parse(cached));
          } catch {
            clearAuth();
            setUser(null);
          }
        }
      } finally {
        setIsLoading(false);
      }
    }

    async function tryRefresh(): Promise<boolean> {
      const refreshToken = localStorage.getItem("refresh_token");
      if (!refreshToken) return false;

      try {
        const res = await fetch("/api/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });

        if (!res.ok) return false;

        const data = await res.json();
        localStorage.setItem("access_token", data.access_token);

        // Re-fetch user with new token
        const meRes = await fetch("/api/auth/me", {
          headers: { Authorization: `Bearer ${data.access_token}` },
        });

        if (meRes.ok) {
          const meData = await meRes.json();
          setUser(meData);
          localStorage.setItem("auth_user", JSON.stringify(meData));
          return true;
        }

        return false;
      } catch {
        return false;
      }
    }

    init();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
      const body = await res.text();
      let message = "Login failed";
      try {
        const parsed = JSON.parse(body);
        if (typeof parsed.detail === "string") message = parsed.detail;
        else if (typeof parsed.message === "string") message = parsed.message;
        else message = body;
      } catch {
        message = body || "Login failed";
      }
      throw new Error(message);
    }

    const data = await res.json();
    storeAuth(data.access_token, data.refresh_token, data.user);
    setUser(data.user);
  }, []);

  const signup = useCallback(
    async (email: string, password: string, displayName: string, orgName: string) => {
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, display_name: displayName, org_name: orgName }),
      });

      if (!res.ok) {
        const body = await res.text();
        let message = "Signup failed";
        try {
          const parsed = JSON.parse(body);
          if (typeof parsed.detail === "string") message = parsed.detail;
          else if (typeof parsed.message === "string") message = parsed.message;
          else message = body;
        } catch {
          message = body || "Signup failed";
        }
        throw new Error(message);
      }

      const data = await res.json();
      storeAuth(data.access_token, data.refresh_token, data.user);
      setUser(data.user);
    },
    [],
  );

  const logout = useCallback(() => {
    clearAuth();
    setUser(null);
  }, []);

  const acceptInvite = useCallback(
    async (inviteId: string, password: string, displayName: string) => {
      const res = await fetch("/api/auth/accept-invite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ invite_id: inviteId, password, display_name: displayName }),
      });

      if (!res.ok) {
        const body = await res.text();
        let message = "Accept invite failed";
        try {
          const parsed = JSON.parse(body);
          if (typeof parsed.detail === "string") message = parsed.detail;
          else if (typeof parsed.message === "string") message = parsed.message;
          else message = body;
        } catch {
          message = body || "Accept invite failed";
        }
        throw new Error(message);
      }

      const data = await res.json();
      storeAuth(data.access_token, data.refresh_token, data.user);
      setUser(data.user);
    },
    [],
  );

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        signup,
        logout,
        acceptInvite,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
