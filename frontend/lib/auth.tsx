"use client";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, getToken, setToken, type AuthUser } from "./api";

type Ctx = {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  has: (perm: string) => boolean;
};

const AuthCtx = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) { setLoading(false); return; }
    api.me().then(setUser).catch(() => setToken(null)).finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const { token, user } = await api.login(email, password);
    setToken(token);
    setUser(user);
  }

  function logout() {
    setToken(null);
    setUser(null);
    router.push("/login");
  }

  const has = (perm: string) => !!user?.permissions.includes(perm);

  return <AuthCtx.Provider value={{ user, loading, login, logout, has }}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const c = useContext(AuthCtx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

/** Redirects to /login when there's no authenticated user.
 *  /word-addin manages its own auth (it runs inside Word), so it's exempt. */
export function isPublicShell(path: string): boolean {
  return path === "/login" || path.startsWith("/word-addin");
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const isPublic = isPublicShell(path);

  useEffect(() => {
    if (!loading && !user && !isPublic) router.replace("/login");
  }, [loading, user, isPublic, router]);

  if (isPublic) return <>{children}</>;
  if (loading) return <div className="container muted">Loading…</div>;
  if (!user) return <div className="container muted">Redirecting to sign in…</div>;
  return <>{children}</>;
}
