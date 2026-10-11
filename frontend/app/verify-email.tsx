import React, { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { useRouter } from "expo-router";
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
  input: { height: 56, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, fontFamily: fonts.text, fontSize: 24, letterSpacing: 8, textAlign: "center", color: c.onSurface, backgroundColor: c.surfaceSecondary },
  error: { fontFamily: fonts.text, fontSize: 13, color: c.error, fontWeight: "600" },
}));

/** Confirms the account email with the 6-digit code sent at sign-up (unverified accounts can't be linked to). */
export default function VerifyEmail() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const toast = useToast();
  const { user, confirmEmail, requestEmailCode } = useSession();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const close = () => (router.canGoBack() ? router.back() : router.replace("/(tabs)/home"));

  const confirm = async () => {
    if (busy) return;
    setError(null);
    if (!/^\d{6}$/.test(code.trim())) return setError("Enter the 6-digit code from the email");
    setBusy(true);
    try {
      await confirmEmail(code.trim());
      toast.show("Email confirmed ✨", "success");
      close();
    } catch (e: any) {
      setError(e.message ?? "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await requestEmailCode();
      toast.show("New code sent ✉️", "success");
    } catch (e: any) {
      setError(e.message ?? "Couldn't send a new code");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={s.root} testID="verify-email-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="verify-close" style={s.round} onPress={close}>
          <Ionicons name="close" size={22} color={colors.onSurface} />
        </Pressable>
      </View>
      <KeyboardAwareScrollView contentContainerStyle={s.body} bottomOffset={120}>
        <View style={{ gap: 6 }}>
          <Text style={s.title}>Confirm your email</Text>
          <Text style={s.sub}>We sent a 6-digit code to {user?.email ?? "your email"}. It expires in 15 minutes.</Text>
        </View>
        <TextInput testID="verify-code" style={s.input} value={code} onChangeText={setCode} placeholder="••••••" placeholderTextColor={colors.muted} keyboardType="number-pad" maxLength={6} textContentType="oneTimeCode" autoFocus />
        {error ? <Text style={s.error} testID="verify-error">{error}</Text> : null}
        <Button title="Confirm" testID="verify-submit" onPress={confirm} loading={busy} />
        <Button title="Send a new code" variant="ghost" testID="verify-resend" onPress={resend} disabled={busy} />
        <Button title="Later" variant="ghost" testID="verify-later" onPress={close} />
      </KeyboardAwareScrollView>
    </View>
  );
}
