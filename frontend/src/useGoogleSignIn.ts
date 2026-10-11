import { useState } from "react";
import { Platform } from "react-native";
import * as Google from "expo-auth-session/providers/google";
import * as WebBrowser from "expo-web-browser";

import { useSession } from "@/src/session";

WebBrowser.maybeCompleteAuthSession();

const CLIENT_IDS = {
  iosClientId: process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID,
  androidClientId: process.env.EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID,
  webClientId: process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID,
};
/** Google sign-in is offered only when THIS platform has an OAuth client id (the backend verifies the token's
 * audience against GOOGLE_CLIENT_IDS). */
export const googleConfigured = Boolean(Platform.select({ ios: CLIENT_IDS.iosClientId, android: CLIENT_IDS.androidClientId, default: CLIENT_IDS.webClientId }));
// expo-auth-session throws during render when the current platform's id is missing, so unconfigured builds get an
// inert placeholder — the button is hidden (`ready` false) and the request is never prompted.
const HOOK_IDS = {
  iosClientId: CLIENT_IDS.iosClientId || "unconfigured",
  androidClientId: CLIENT_IDS.androidClientId || "unconfigured",
  webClientId: CLIENT_IDS.webClientId || "unconfigured",
};

/**
 * Native Google Sign-In: Google returns an ID token to the app, the backend verifies it (signature, audience,
 * email_verified). Replaces the Emergent demo-auth redirect flow (audit H3/N14 — the OAuth `state` is handled by
 * expo-auth-session).
 */
export function useGoogleSignIn(onSignedIn: () => void, onError: (message: string) => void) {
  const { googleLogin } = useSession();
  const [request, , promptAsync] = Google.useIdTokenAuthRequest(HOOK_IDS);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    if (!googleConfigured) return;
    setBusy(true);
    try {
      const result = await promptAsync();
      if (result.type === "cancel" || result.type === "dismiss") return;
      const idToken = result.type === "success" ? result.params?.id_token : undefined;
      if (!idToken) return onError("Google sign-in didn’t complete");
      await googleLogin(idToken);
      onSignedIn();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Google sign-in failed");
    } finally {
      setBusy(false);
    }
  };
  return { start, busy, ready: googleConfigured && !!request };
}
