import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import Purchases from "react-native-purchases";
import { useQueryClient } from "@tanstack/react-query";

import { ApiError, api, getToken, rotateGuestId, setPremiumFlag, setToken, setUnauthorizedHandler, track, type User } from "@/src/api";
import { rcEnabled, useSubscription } from "@/src/revenuecat";
import { storage } from "@/src/utils/storage";

const USER_CACHE_KEY = "datespark_user_cache";

type Session = {
  user: User | null;
  ready: boolean;
  isPremium: boolean;
  isAdmin: boolean;
  identityError: string | null;
  login: (email: string, password: string) => Promise<User>;
  signup: (name: string, email: string, password: string) => Promise<User>;
  appleLogin: (identityToken: string, name: string | null, authorizationCode: string | null) => Promise<User>;
  googleLogin: (idToken: string) => Promise<User>;
  requestEmailCode: () => Promise<void>;
  confirmEmail: (code: string) => Promise<User>;
  forgotPassword: (email: string) => Promise<void>;
  resetPassword: (email: string, code: string, newPassword: string) => Promise<User>;
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

  const rememberUser = useCallback(async (u: User | null) => {
    setUser(u);
    await storage.setItem(USER_CACHE_KEY, u ? JSON.stringify(u) : null);
  }, []);

  const refresh = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      await rememberUser(null);
      return;
    }
    try {
      await rememberUser(await api<User>("/auth/me"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await setToken(null);
        await rememberUser(null);
      } else {
        // Offline or a server hiccup: stay signed in with the last known profile (audit H6).
        const cached = await storage.getItem<string | null>(USER_CACHE_KEY, null);
        setUser(cached ? (JSON.parse(cached) as User) : null);
      }
    }
  }, [rememberUser]);

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
    await rememberUser(data.user);
    queryClient.invalidateQueries({ queryKey: ["sparks"] });
    return data.user;
  };

  const logout = useCallback(async () => {
    await setToken(null);
    await rememberUser(null);
    await rotateGuestId();
    queryClient.removeQueries({ queryKey: ["sparks"] });
  }, [queryClient, rememberUser]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await refresh();
      if (!cancelled) {
        setReady(true);
        track("app_opened");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  // The server rejected our token mid-session (expired, revoked, account deleted): sign out cleanly.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      logout();
    });
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  const googleLogin = useCallback(async (idToken: string) => {
    track("signup_started", { provider: "google" });
    return afterAuth(await api("/auth/google", { method: "POST", json: { id_token: idToken } }));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const login = useCallback(async (email: string, password: string) => afterAuth(await api("/auth/login", { method: "POST", json: { email, password } })), []); // eslint-disable-line react-hooks/exhaustive-deps
  const signup = useCallback(async (name: string, email: string, password: string) => {
    track("signup_started");
    return afterAuth(await api("/auth/signup", { method: "POST", json: { name, email, password } }));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const appleLogin = useCallback(async (identityToken: string, name: string | null, authorizationCode: string | null) => {
    track("signup_started", { provider: "apple" });
    return afterAuth(await api("/auth/apple", { method: "POST", json: { identity_token: identityToken, name, authorization_code: authorizationCode } }));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const requestEmailCode = useCallback(async () => {
    await api("/auth/verify-email/request", { method: "POST" });
  }, []);

  const confirmEmail = useCallback(async (code: string) => {
    const u = await api<User>("/auth/verify-email/confirm", { method: "POST", json: { code } });
    await rememberUser(u);
    return u;
  }, [rememberUser]);

  const forgotPassword = useCallback(async (email: string) => {
    await api("/auth/password/forgot", { method: "POST", json: { email } });
  }, []);

  const resetPassword = useCallback(async (email: string, code: string, newPassword: string) => afterAuth(await api("/auth/password/reset", { method: "POST", json: { email, code, new_password: newPassword } })), []); // eslint-disable-line react-hooks/exhaustive-deps

  const deleteAccount = useCallback(async () => {
    await api("/auth/account", { method: "DELETE" });
    await logout();
  }, [logout]);

  return (
    <Ctx.Provider value={{ user, ready, isPremium, isAdmin, identityError, login, signup, appleLogin, googleLogin, requestEmailCode, confirmEmail, forgotPassword, resetPassword, logout, refresh, deleteAccount }}>
      {children}
    </Ctx.Provider>
  );
}

export function useSession() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
