import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import Purchases from "react-native-purchases";
import { useQueryClient } from "@tanstack/react-query";

import { api, getToken, setPremiumFlag, setToken, track, type User } from "@/src/api";
import { rcEnabled, useSubscription } from "@/src/revenuecat";

type Session = {
  user: User | null;
  ready: boolean;
  isPremium: boolean;
  isAdmin: boolean;
  identityError: string | null;
  login: (email: string, password: string) => Promise<User>;
  signup: (name: string, email: string, password: string) => Promise<User>;
  appleLogin: (identityToken: string, name: string | null, email: string | null) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  deleteAccount: () => Promise<void>;
};

const Ctx = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [identityError, setIdentityError] = useState<string | null>(null);
  const rcIdentityRef = useRef<string | null>(null);
  const { isSubscribed, isTrial, expirationDate } = useSubscription();
  const queryClient = useQueryClient();

  const isAdmin = user?.role === "admin";
  const isPremium = isSubscribed || isAdmin;

  useEffect(() => {
    setPremiumFlag(isPremium);
  }, [isPremium]);

  const refresh = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      setUser(null);
      return;
    }
    try {
      setUser(await api<User>("/auth/me"));
    } catch {
      await setToken(null);
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh().finally(() => {
      setReady(true);
      track("app_opened");
    });
  }, [refresh]);

  // Bind RevenueCat identity to the backend user id on every auth path.
  useEffect(() => {
    if (!rcEnabled) return;
    (async () => {
      try {
        if (user?.id && rcIdentityRef.current !== user.id) {
          const { customerInfo } = await Purchases.logIn(user.id);
          rcIdentityRef.current = user.id;
          queryClient.setQueryData(["revenuecat", "customer-info"], customerInfo);
          setIdentityError(null);
        } else if (!user?.id && rcIdentityRef.current) {
          const info = await Purchases.logOut();
          rcIdentityRef.current = null;
          queryClient.setQueryData(["revenuecat", "customer-info"], info);
        }
      } catch (e) {
        setIdentityError(String(e));
      }
    })();
  }, [user?.id, queryClient]);

  // Mirror the store entitlement to the backend for reporting (not enforcement).
  useEffect(() => {
    if (!user || isAdmin) return;
    const status = isSubscribed ? (isTrial ? "trial" : "premium") : "free";
    if (status === user.subscription_status) return;
    api("/users/me/subscription", { method: "PUT", json: { status, renewal_date: expirationDate } })
      .then(() => setUser((u) => (u ? { ...u, subscription_status: status } : u)))
      .catch(() => {});
  }, [user, isAdmin, isSubscribed, isTrial, expirationDate]);

  const afterAuth = async (data: { access_token: string; user: User }) => {
    await setToken(data.access_token);
    setUser(data.user);
    queryClient.invalidateQueries({ queryKey: ["sparks"] });
    return data.user;
  };

  const login = useCallback(async (email: string, password: string) => afterAuth(await api("/auth/login", { method: "POST", json: { email, password } })), []); // eslint-disable-line react-hooks/exhaustive-deps
  const signup = useCallback(async (name: string, email: string, password: string) => {
    track("signup_started");
    return afterAuth(await api("/auth/signup", { method: "POST", json: { name, email, password } }));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const appleLogin = useCallback(async (identityToken: string, name: string | null, email: string | null) => {
    track("signup_started", { provider: "apple" });
    return afterAuth(await api("/auth/apple", { method: "POST", json: { identity_token: identityToken, name, email } }));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const logout = useCallback(async () => {
    await setToken(null);
    setUser(null);
    queryClient.invalidateQueries({ queryKey: ["sparks"] });
  }, [queryClient]);

  const deleteAccount = useCallback(async () => {
    await api("/auth/account", { method: "DELETE" });
    await logout();
  }, [logout]);

  return (
    <Ctx.Provider value={{ user, ready, isPremium, isAdmin, identityError, login, signup, appleLogin, logout, refresh, deleteAccount }}>
      {children}
    </Ctx.Provider>
  );
}

export function useSession() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
