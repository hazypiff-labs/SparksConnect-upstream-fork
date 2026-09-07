import React, { useEffect, useState } from "react";
import { Platform, Pressable, Text, TextInput, View } from "react-native";
import * as AppleAuthentication from "expo-apple-authentication";
import { useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { KeyboardAwareScrollView, KeyboardStickyView } from "react-native-keyboard-controller";

import { Button, SparkGlyph, StickyFooter, useToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.lg, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: spacing.md },
  round: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  body: { paddingHorizontal: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xl },
  title: { fontFamily: fonts.display, fontSize: 30, fontWeight: "700", color: c.onSurface },
  sub: { fontFamily: fonts.text, fontSize: 15, color: c.muted, lineHeight: 22 },
  segment: { flexDirection: "row", backgroundColor: c.surfaceTertiary, borderRadius: radius.pill, padding: 4 },
  segItem: { flex: 1, height: 40, alignItems: "center", justifyContent: "center", borderRadius: radius.pill },
  segActive: { backgroundColor: c.surfaceSecondary },
  segText: { fontFamily: fonts.text, fontSize: 14, fontWeight: "600", color: c.muted },
  segTextActive: { color: c.onSurface },
  label: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: c.onSurfaceTertiary, marginBottom: 6 },
  input: { height: 52, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, fontFamily: fonts.text, fontSize: 16, color: c.onSurface, backgroundColor: c.surfaceSecondary },
  error: { fontFamily: fonts.text, fontSize: 13, color: c.error, fontWeight: "600" },
  note: { fontFamily: fonts.text, fontSize: 13, color: c.muted, lineHeight: 19, textAlign: "center" },
  dividerRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  dividerLine: { flex: 1, height: 1, backgroundColor: c.divider },
  dividerText: { fontFamily: fonts.text, fontSize: 13, color: c.muted, fontWeight: "600" },
  appleButton: { height: 52, width: "100%" },
}));

export default function Auth() {
  const params = useLocalSearchParams<{ mode?: string }>();
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const toast = useToast();
  const { login, signup, appleLogin } = useSession();
  const [appleAvailable, setAppleAvailable] = useState(false);
  const [appleBusy, setAppleBusy] = useState(false);
  useEffect(() => {
    if (Platform.OS === "ios") AppleAuthentication.isAvailableAsync().then(setAppleAvailable).catch(() => setAppleAvailable(false));
  }, []);

  const signInWithApple = async () => {
    setError(null);
    setAppleBusy(true);
    try {
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [AppleAuthentication.AppleAuthenticationScope.FULL_NAME, AppleAuthentication.AppleAuthenticationScope.EMAIL],
      });
      if (!credential.identityToken) throw new Error("Apple didn’t return a sign-in token");
      const fullName = [credential.fullName?.givenName, credential.fullName?.familyName].filter(Boolean).join(" ") || null;
      const user = await appleLogin(credential.identityToken, fullName, credential.email ?? null);
      toast.show(`Welcome, ${user.name.split(" ")[0]} ✨`, "success");
      if (router.canGoBack()) router.back();
      else router.replace("/(tabs)/home");
    } catch (e: any) {
      if (e?.code === "ERR_REQUEST_CANCELED") return;
      setError(e?.message ?? "Apple sign-in failed");
    } finally {
      setAppleBusy(false);
    }
  };
  const [mode, setMode] = useState<"login" | "signup">(params.mode === "signup" ? "signup" : "login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    if (!email.trim() || !password) return setError("Email and password are required");
    if (mode === "signup" && !name.trim()) return setError("Tell us your name");
    if (mode === "signup" && password.length < 8) return setError("Password must be at least 8 characters");
    setBusy(true);
    try {
      const user = mode === "login" ? await login(email.trim(), password) : await signup(name.trim(), email.trim(), password);
      toast.show(mode === "login" ? `Welcome back, ${user.name.split(" ")[0]} ✨` : "Account created — your Sparks are safe ✨", "success");
      if (router.canGoBack()) router.back();
      else router.replace("/(tabs)/home");
    } catch (e: any) {
      setError(e.message ?? "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={s.root} testID="auth-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="auth-close" style={s.round} onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/home"))}>
          <Ionicons name="close" size={22} color={colors.onSurface} />
        </Pressable>
        <SparkGlyph size={24} />
      </View>
      <KeyboardAwareScrollView contentContainerStyle={s.body} bottomOffset={120}>
        <View style={{ gap: 6 }}>
          <Text style={s.title}>{mode === "login" ? "Welcome back" : "Keep your Sparks"}</Text>
          <Text style={s.sub}>{mode === "login" ? "Log in to pick up where you left off." : "Create a free account so your saved and shared Sparks follow you anywhere."}</Text>
        </View>
        <View style={s.segment} testID="auth-mode-toggle">
          {(["login", "signup"] as const).map((m) => (
            <Pressable key={m} testID={`auth-mode-${m}`} onPress={() => setMode(m)} style={[s.segItem, mode === m && s.segActive]}>
              <Text style={[s.segText, mode === m && s.segTextActive]}>{m === "login" ? "Log In" : "Sign Up"}</Text>
            </Pressable>
          ))}
        </View>
        {mode === "signup" ? (
          <View>
            <Text style={s.label}>Name</Text>
            <TextInput testID="auth-name-input" style={s.input} value={name} onChangeText={setName} placeholder="Your first name" placeholderTextColor={colors.muted} autoCapitalize="words" textContentType="name" />
          </View>
        ) : null}
        <View>
          <Text style={s.label}>Email</Text>
          <TextInput testID="auth-email-input" style={s.input} value={email} onChangeText={setEmail} placeholder="you@example.com" placeholderTextColor={colors.muted} autoCapitalize="none" keyboardType="email-address" textContentType="emailAddress" autoComplete="email" />
        </View>
        <View>
          <Text style={s.label}>Password</Text>
          <TextInput testID="auth-password-input" style={s.input} value={password} onChangeText={setPassword} placeholder={mode === "signup" ? "At least 8 characters" : "Your password"} placeholderTextColor={colors.muted} secureTextEntry textContentType={mode === "signup" ? "newPassword" : "password"} returnKeyType="go" onSubmitEditing={submit} />
        </View>
        {error ? <Text style={s.error} testID="auth-error">{error}</Text> : null}
        {appleAvailable ? (
          <View style={{ gap: spacing.lg }} testID="apple-signin-section">
            <View style={s.dividerRow}>
              <View style={s.dividerLine} />
              <Text style={s.dividerText}>or</Text>
              <View style={s.dividerLine} />
            </View>
            <AppleAuthentication.AppleAuthenticationButton
              testID="apple-signin-button"
              buttonType={mode === "login" ? AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN : AppleAuthentication.AppleAuthenticationButtonType.SIGN_UP}
              buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.BLACK}
              cornerRadius={26}
              style={[s.appleButton, appleBusy && { opacity: 0.6 }]}
              onPress={appleBusy ? () => {} : signInWithApple}
            />
          </View>
        ) : null}
        <Text style={s.note}>{appleAvailable ? "Google sign-in is coming soon." : "Apple sign-in is available on iPhone; Google is coming soon."} We only store what’s needed to keep your Sparks.</Text>
      </KeyboardAwareScrollView>
      <KeyboardStickyView>
        <StickyFooter>
          <Button title={mode === "login" ? "Log In" : "Create Account ✨"} testID="auth-submit-button" onPress={submit} loading={busy} />
        </StickyFooter>
      </KeyboardStickyView>
    </View>
  );
}
