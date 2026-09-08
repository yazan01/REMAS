"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { api, getToken, setToken, type Me } from "./api";

type SessionValue = {
  me: Me | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signIn: (token: string) => Promise<void>;
  signOut: () => void;
};

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      setMe(await api<Me>("/auth/me"));
    } catch {
      setToken(null);
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(
    async (token: string) => {
      setToken(token);
      setLoading(true);
      await refresh();
    },
    [refresh],
  );

  const signOut = useCallback(() => {
    setToken(null);
    setMe(null);
  }, []);

  return (
    <SessionContext.Provider value={{ me, loading, refresh, signIn, signOut }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}

/** Redirects to sign-in once the session is known to be absent. */
export function useRequireSession() {
  const { me, loading } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [loading, me, router]);

  return { me, loading };
}
