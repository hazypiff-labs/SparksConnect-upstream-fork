import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { router } from "expo-router";
import Purchases from "react-native-purchases";
import { useQueryClient } from "@tanstack/react-query";

import { api, getToken, setPremiumFlag, setToken, track, type User } from "@/src/api";
import { rcEnabled, useSubscription } from "@/src/revenuecat";

WebBrowser.maybeCompleteAuthSession();

const exchangedSessionIds = new Set<string>();

function extractSessionId(url: string | null | undefined): string | null {
  if (!url) return null;
  const m = url.match(/[?#&]session_id=([^&#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

function stripSessionIdFromWebUrl() {
  if (Platform.OS !== "web" || typeof window === "undefined") return;
  const clean = (s: string, lead: string) => {
    const parts = s.replace(/^[?#]/, "").split("&").filter((p) => p && !p.startsWith("session_id="));
    return parts.length ? lead + parts.join("&") : "";
  };
  const url = window.location.pathname + clean(window.location.search, "?") + clean(window.location.hash, "#");
  window.history.replaceState(window.history.state, "", url);
}

type Session = {
  user: User | null;
  ready: boolean;
  isPremium: boolean;
  isAdmin: boolean;
  identityError: string | null;
  login: (email: string, password: string) => Promise<User>;
  signup: (name: string, email: string, password: string) => Promise<User>;
  appleLogin: (identityToken: string, name: string | null, email: string | null) => Promise<User>;
  googleLogin: () => Promise<void>;
  googleBusy: boolean;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  deleteAccount: () => Promise<void>;
};

const Ctx = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [identityError, setIdentityError] = useState<string | null>(null);
  const [googleBusy, setGoogleBusy] = useState(false);
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

  // Exchange an Emergent Google Auth session_id (one-time) for our own JWT.
  const exchangeSessionId = useCallback(async (sessionId: string): Promise<boolean> => {
    if (exchangedSessionIds.has(sessionId)) return false;
    exchangedSessionIds.add(sessionId);
    try {
      await afterAuth(await api("/auth/session", { method: "POST", json: { session_id: sessionId } }));
      stripSessionIdFromWebUrl();
      router.replace("/(tabs)/home");
      return true;
    } catch (e) {
      setIdentityError(e instanceof Error ? e.message : "Google sign-in failed");
      return false;
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let sid: string | null = null;
      if (Platform.OS === "web" && typeof window !== "undefined") {
        sid = extractSessionId(window.location.hash) ?? extractSessionId(window.location.search);
      } else {
        sid = extractSessionId(await Linking.getInitialURL());
      }
      if (sid) await exchangeSessionId(sid);
      else await refresh();
      if (!cancelled) {
        setReady(true);
        track("app_opened");
      }
    })();
    const sub = Linking.addEventListener("url", ({ url }) => {
      const sid = extractSessionId(url);
      if (sid) exchangeSessionId(sid);
    });
    return () => {
      cancelled = true;
      sub.remove();
    };
  }, [refresh, exchangeSessionId]);

  const googleLogin = useCallback(async () => {
    track("signup_started", { provider: "google" });
    if (Platform.OS === "web" && typeof window !== "undefined") {
      const redirectUrl = window.location.origin + "/";
      window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
      return;
    }
    setGoogleBusy(true);
    let captured: string | null = null;
    const sub = Linking.addEventListener("url", ({ url }) => {
      captured = captured ?? url;
    });
    try {
      const redirectUrl = Linking.createURL("");
      const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
      const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
      const url = (result.type === "success" ? result.url : null) ?? captured ?? (await Linking.getInitialURL());
      const sid = extractSessionId(url);
      if (sid) await exchangeSessionId(sid);
      else if (result.type !== "cancel" && result.type !== "dismiss") setIdentityError("Google sign-in didn’t complete");
    } finally {
      sub.remove();
      setGoogleBusy(false);
    }
  }, [exchangeSessionId]);

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
    <Ctx.Provider value={{ user, ready, isPremium, isAdmin, identityError, login, signup, appleLogin, googleLogin, googleBusy, logout, refresh, deleteAccount }}>
      {children}
    </Ctx.Provider>
  );
}

export function useSession() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
