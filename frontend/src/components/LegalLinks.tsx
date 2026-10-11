import React from "react";
import { Linking, Text } from "react-native";

import { LEGAL } from "@/src/constants";
import { fonts, makeStyles } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  text: { fontFamily: fonts.text, fontSize: 12, color: c.muted, lineHeight: 18, textAlign: "center" },
  link: { color: c.onSurface, textDecorationLine: "underline" },
}));

/** "Terms of Use · Privacy Policy" — required next to sign-up and on the subscription paywall. */
export function LegalLinks({ prefix }: { prefix?: string }) {
  const s = useStyles();
  const open = (url: string) => url && Linking.openURL(url).catch(() => {});
  return (
    <Text style={s.text} testID="legal-links">
      {prefix ? `${prefix} ` : ""}
      <Text style={s.link} onPress={() => open(LEGAL.terms)} accessibilityRole="link">Terms of Use</Text>
      {" · "}
      {LEGAL.privacy ? (
        <Text style={s.link} onPress={() => open(LEGAL.privacy)} accessibilityRole="link">Privacy Policy</Text>
      ) : (
        <Text>{__DEV__ ? "Privacy Policy (set EXPO_PUBLIC_PRIVACY_URL)" : "Privacy Policy"}</Text>
      )}
    </Text>
  );
}
