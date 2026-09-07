import React from "react";
import { Text, View } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import Animated, { FadeInDown, FadeInUp } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Ionicons from "@react-native-vector-icons/ionicons";

import { track } from "@/src/api";
import { Button, SparkGlyph } from "@/src/components/ui";
import { IMAGES } from "@/src/constants";
import { useSession } from "@/src/session";
import { fonts, makeStyles, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceInverse },
  image: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  scrim: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  content: { flex: 1, paddingHorizontal: spacing.xl, justifyContent: "space-between" },
  brandRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  brand: { fontFamily: fonts.display, fontSize: 20, fontWeight: "700", color: c.onSurfaceInverse, letterSpacing: 3 },
  hero: { gap: spacing.md },
  headline: { fontFamily: fonts.display, fontSize: 48, lineHeight: 54, fontWeight: "700", color: c.onSurfaceInverse, letterSpacing: -0.5 },
  sub: { fontFamily: fonts.text, fontSize: 18, lineHeight: 26, color: c.onSurfaceInverse, opacity: 0.9, maxWidth: 320 },
  actions: { gap: spacing.md },
}));

export default function Welcome() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { googleLogin, googleBusy } = useSession();
  return (
    <View style={s.root} testID="welcome-screen">
      <Image source={{ uri: IMAGES.welcome }} style={s.image} contentFit="cover" transition={500} />
      <LinearGradient colors={[colors.scrimLight, colors.scrimLight, colors.scrim]} locations={[0, 0.45, 1]} style={s.scrim} />
      <View style={[s.content, { paddingTop: insets.top + spacing.xl, paddingBottom: Math.max(insets.bottom, spacing.lg) + spacing.lg }]}>
        <Animated.View entering={FadeInDown.duration(500)} style={s.brandRow}>
          <Text style={s.brand}>DATE SPARK</Text>
          <SparkGlyph size={22} />
        </Animated.View>
        <View style={{ gap: spacing.xxl }}>
          <Animated.View entering={FadeInUp.delay(150).duration(600)} style={s.hero}>
            <Text style={s.headline} testID="welcome-headline">Create the moment.</Text>
            <Text style={s.sub}>Discover experiences that bring people closer together.</Text>
          </Animated.View>
          <Animated.View entering={FadeInUp.delay(350).duration(600)} style={s.actions}>
            <Button
              title="Create a Spark ✨"
              testID="welcome-create-button"
              onPress={() => {
                track("spark_started", { from: "welcome" });
                router.replace("/(tabs)/create");
              }}
            />
            <Button
              title="Continue with Google"
              variant="glass"
              testID="welcome-google-button"
              loading={googleBusy}
              onPress={() => googleLogin().catch(() => {})}
              icon={<Ionicons name="logo-google" size={18} color={colors.onSurfaceInverse} />}
            />
            <Button title="Log In" variant="ghost" testID="welcome-login-button" onPress={() => router.push({ pathname: "/auth", params: { mode: "login" } })} style={{ opacity: 0.95 }} />
            <Button title="Explore first" variant="ghost" testID="welcome-explore-button" onPress={() => router.replace("/(tabs)/home")} style={{ opacity: 0.9 }} />
          </Animated.View>
        </View>
      </View>
    </View>
  );
}
