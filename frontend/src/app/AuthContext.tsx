import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, setCsrfToken } from "../api/client";
import type { AuthResponse, User } from "../api/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<User | null>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const applyAuth = useCallback((response: AuthResponse) => {
    const hydrated = response.user;
    setCsrfToken(hydrated.csrf_token);
    setUser(hydrated);
    setError(null);
    return hydrated;
  }, []);

  const refresh = useCallback(async () => {
    try {
      const response = await api.get<AuthResponse>("/auth/me");
      return applyAuth(response);
    } catch (caught) {
      setCsrfToken(null);
      setUser(null);
      if (caught instanceof ApiError && caught.status !== 401) setError(caught.message);
      return null;
    }
  }, [applyAuth]);

  useEffect(() => {
    void refresh().finally(() => setLoading(false));
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    setError(null);
    const response = await api.post<AuthResponse>("/auth/login", { username, password });
    applyAuth(response);
  }, [applyAuth]);

  const logout = useCallback(async () => {
    try {
      await api.post<void>("/auth/logout");
    } finally {
      setCsrfToken(null);
      setUser(null);
    }
  }, []);

  const value = useMemo(() => ({ user, loading, error, login, logout, refresh }), [user, loading, error, login, logout, refresh]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

