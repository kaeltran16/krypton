import { useState, useEffect, useCallback } from "react";
import { api, resetUnauthorizedFlag, type AuthUser } from "../../../shared/lib/api";

// In-memory token for WebSocket auth (httpOnly cookie is not readable from JS)
let wsToken: string | null = null;
export function getWsToken() { return wsToken; }

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const res = await api.authMe();
      wsToken = res.token;
      setUser(res.user);
    } catch {
      setUser(null);
      wsToken = null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();

    const handleUnauthorized = () => {
      setUser(null);
      wsToken = null;
    };
    window.addEventListener("auth:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("auth:unauthorized", handleUnauthorized);
  }, [checkAuth]);

  const login = useCallback(async (googleIdToken: string) => {
    const { token, user: userData } = await api.authGoogle(googleIdToken);
    wsToken = token;
    resetUnauthorizedFlag();
    setUser(userData);
  }, []);

  const logout = useCallback(async () => {
    await api.authLogout();
    setUser(null);
    wsToken = null;
  }, []);

  return {
    user,
    isLoading,
    isAuthenticated: !!user,
    login,
    logout,
  };
}
