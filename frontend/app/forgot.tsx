import React, { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

import { Button, useToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md },
  round: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  body: { paddingHorizontal: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xl },
  title: { fontFamily: fonts.display, fontSize: 30, fontWeight: "700", color: c.onSurface },
  sub: { fontFamily: fonts.text, fontSize: 15, color: c.muted, lineHeight: 22 },
  label: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: c.onSurfaceTertiary, marginBottom: 6 },
  input: { height: 52, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, fontFamily: fonts.text, fontSize: 16, color: c.onSurface, backgroundColor: c.surfaceSecondary },
  error: { fontFamily: fonts.text, fontSize: 13, color: c.error, fontWeight: "600" },
}));

/** Password reset: request a 6-digit code by email, then set a new password (signs in and revokes old sessions). */
export default function Forgot() {
  const params = useLocalSearchParams<{ email?: string }>();
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const toast = useToast();
  const { forgotPassword, resetPassword } = useSession();
  const [email, setEmail] = useState(params.email ?? "");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setError(null);
    if (!email.trim()) return setError("Enter the email you signed up with");
    setBusy(true);
    try {
      await forgotPassword(email.trim());
      setSent(true);
      toast.show("If that email has an account, a code is on its way ✉️", "success");
    } catch (e: any) {
      setError(e.message ?? "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setError(null);
    if (!/^\d{6}$/.test(code.trim())) return setError("Enter the 6-digit code from the email");
    if (password.length < 8) return setError("Password must be at least 8 characters");
    setBusy(true);
    try {
      await resetPassword(email.trim(), code.trim(), password);
      toast.show("Password updated — you're signed in ✨", "success");
      router.dismissAll();
      router.replace("/(tabs)/home");
    } catch (e: any) {
      setError(e.message ?? "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={s.root} testID="forgot-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="forgot-close" style={s.round} onPress={() => router.back()}>
          <Ionicons name="close" size={22} color={colors.onSurface} />
        </Pressable>
      </View>
      <KeyboardAwareScrollView contentContainerStyle={s.body} bottomOffset={120}>
        <View style={{ gap: 6 }}>
          <Text style={s.title}>Reset password</Text>
          <Text style={s.sub}>{sent ? "Enter the code we emailed you and choose a new password." : "We'll email you a 6-digit code."}</Text>
        </View>
        <View>
          <Text style={s.label}>Email</Text>
          <TextInput testID="forgot-email" style={s.input} value={email} onChangeText={setEmail} editable={!sent} placeholder="you@example.com" placeholderTextColor={colors.muted} autoCapitalize="none" keyboardType="email-address" textContentType="emailAddress" />
        </View>
        {sent ? (
          <>
            <View>
              <Text style={s.label}>Code</Text>
              <TextInput testID="forgot-code" style={s.input} value={code} onChangeText={setCode} placeholder="123456" placeholderTextColor={colors.muted} keyboardType="number-pad" maxLength={6} textContentType="oneTimeCode" />
            </View>
            <View>
              <Text style={s.label}>New password</Text>
              <TextInput testID="forgot-password" style={s.input} value={password} onChangeText={setPassword} placeholder="At least 8 characters" placeholderTextColor={colors.muted} secureTextEntry textContentType="newPassword" />
            </View>
          </>
        ) : null}
        {error ? <Text style={s.error} testID="forgot-error">{error}</Text> : null}
        <Button title={sent ? "Set new password" : "Email me a code"} testID="forgot-submit" onPress={sent ? reset : send} loading={busy} />
        {sent ? <Button title="Send a new code" variant="ghost" testID="forgot-resend" onPress={send} disabled={busy} /> : null}
      </KeyboardAwareScrollView>
    </View>
  );
}
