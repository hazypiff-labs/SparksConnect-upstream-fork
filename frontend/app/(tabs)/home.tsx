import React from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import Ionicons from "@react-native-vector-icons/ionicons";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, track, type Spark } from "@/src/api";
import { Button, SparkGlyph } from "@/src/components/ui";
import { IMAGES, cardImage } from "@/src/constants";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  brand: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onSurface, letterSpacing: 2.5 },
  greeting: { fontFamily: fonts.text, fontSize: 14, color: c.muted },
  hero: { marginHorizontal: spacing.lg, borderRadius: radius.lg + 4, overflow: "hidden", minHeight: 260, backgroundColor: c.surfaceInverse },
  heroImg: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  heroScrim: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  heroContent: { flex: 1, justifyContent: "flex-end", padding: spacing.xl, gap: spacing.md },
  heroTitle: { fontFamily: fonts.display, fontSize: 30, lineHeight: 36, fontWeight: "700", color: c.onSurfaceInverse },
  heroSub: { fontFamily: fonts.text, fontSize: 15, color: c.onSurfaceInverse, opacity: 0.9 },
  section: { paddingHorizontal: spacing.lg, marginTop: spacing.xl, gap: spacing.md },
  sectionTitle: { fontFamily: fonts.display, fontSize: 20, fontWeight: "700", color: c.onSurface },
  promo: { backgroundColor: c.brandTertiary, borderRadius: radius.lg, padding: spacing.lg, flexDirection: "row", alignItems: "center", gap: spacing.md },
  promoText: { flex: 1, fontFamily: fonts.text, fontSize: 14, color: c.onBrandTertiary, fontWeight: "600", lineHeight: 20 },
  usage: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
  featured: { width: 220, borderRadius: radius.lg, overflow: "hidden", height: 150, backgroundColor: c.surfaceInverse, flexShrink: 0 },
  featuredContent: { flex: 1, justifyContent: "flex-end", padding: spacing.lg, gap: 2 },
  featuredTitle: { fontFamily: fonts.display, fontSize: 17, fontWeight: "700", color: c.onSurfaceInverse },
  featuredTag: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceInverse, opacity: 0.9 },
  recent: { flexDirection: "row", gap: spacing.md, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: c.border, alignItems: "center" },
  thumb: { width: 64, height: 64, borderRadius: radius.sm },
  recentTitle: { fontFamily: fonts.display, fontSize: 15, fontWeight: "700", color: c.onSurface },
  recentMeta: { fontFamily: fonts.text, fontSize: 12, color: c.muted, marginTop: 2 },
  steps: { flexDirection: "row", gap: spacing.sm },
  step: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: c.border, gap: 4 },
  stepNum: { fontFamily: fonts.display, fontSize: 12, fontWeight: "700", color: c.brandPrimary },
  stepText: { fontFamily: fonts.text, fontSize: 13, fontWeight: "600", color: c.onSurface },
}));

export default function Home() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user, isPremium } = useSession();

  const config = useQuery({ queryKey: ["config"], queryFn: () => api("/config/public") });
  const mine = useQuery({ queryKey: ["sparks", "mine"], queryFn: () => api<{ recent: Spark[] }>("/sparks/mine") });
  const usage = useQuery({ queryKey: ["sparks", "usage"], queryFn: () => api<{ used: number; limit: number }>("/sparks/usage") });

  const refreshing = config.isRefetching || mine.isRefetching;
  const onRefresh = () => {
    config.refetch();
    mine.refetch();
    usage.refetch();
  };

  const startSpark = () => {
    track("spark_started", { from: "home" });
    router.push("/(tabs)/create");
  };

  return (
    <View style={s.root} testID="home-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.sm }]}>
        <View>
          <Text style={s.brand}>DATE SPARK</Text>
          <Text style={s.greeting} testID="home-greeting">{user ? `Hey ${user.name.split(" ")[0]}, who are you seeing?` : "Find something. Spark a plan. Make a memory."}</Text>
        </View>
        <SparkGlyph size={26} />
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xl }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}>
        <Animated.View entering={FadeInDown.duration(500)} style={s.hero}>
          <Image source={{ uri: IMAGES.share }} style={s.heroImg} contentFit="cover" transition={400} />
          <LinearGradient colors={[colors.transparent, colors.scrimLight, colors.scrim]} style={s.heroScrim} />
          <View style={s.heroContent}>
            <Text style={s.heroTitle}>Tell us who you’re with.{"\n"}We’ll help you create the moment.</Text>
            <Text style={s.heroSub}>Your first Spark takes about 60 seconds.</Text>
            <Button title="Create a Spark ✨" testID="home-create-button" onPress={startSpark} />
          </View>
        </Animated.View>

        <View style={s.section}>
          <View style={s.steps}>
            {["Who you're with", "Pick the vibe", "Budget & distance", "Share the Spark"].map((t, i) => (
              <View key={t} style={s.step}>
                <Text style={s.stepNum}>0{i + 1}</Text>
                <Text style={s.stepText}>{t}</Text>
              </View>
            ))}
          </View>
        </View>

        {!isPremium && config.data ? (
          <View style={s.section}>
            <Pressable testID="home-promo-card" style={s.promo} onPress={() => router.push("/premium")}>
              <Ionicons name="sparkles" size={22} color={colors.onBrandTertiary} />
              <Text style={s.promoText}>{config.data.promo_message}</Text>
              <Ionicons name="chevron-forward" size={18} color={colors.onBrandTertiary} />
            </Pressable>
            {usage.data ? (
              <Text style={s.usage} testID="home-usage-text">
                {Math.max(usage.data.limit - usage.data.used, 0)} of {usage.data.limit} free Sparks left this month
              </Text>
            ) : null}
          </View>
        ) : null}

        {config.data?.featured_experiences?.length ? (
          <View style={s.section}>
            <Text style={s.sectionTitle}>Featured moments</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.md }}>
              {config.data.featured_experiences.map((f: { title: string; tagline: string; vibe: string }, i: number) => (
                <Pressable key={f.title} testID={`featured-${i}`} style={s.featured} onPress={startSpark}>
                  <Image source={{ uri: cardImage(i) }} style={s.heroImg} contentFit="cover" />
                  <LinearGradient colors={[colors.transparent, colors.scrim]} style={s.heroScrim} />
                  <View style={s.featuredContent}>
                    <Text style={s.featuredTitle}>{f.title}</Text>
                    <Text style={s.featuredTag}>{f.tagline}</Text>
                  </View>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        ) : null}

        {mine.data?.recent?.length ? (
          <View style={s.section}>
            <Text style={s.sectionTitle}>Recent Sparks</Text>
            {mine.data.recent.slice(0, 4).map((sp, i) => (
              <Pressable key={sp.id} testID={`recent-spark-${i}`} style={s.recent} onPress={() => router.push(`/spark/${sp.id}`)}>
                <Image source={{ uri: cardImage(i) }} style={s.thumb} contentFit="cover" />
                <View style={{ flex: 1 }}>
                  <Text style={s.recentTitle}>{sp.emoji} {sp.title}</Text>
                  <Text style={s.recentMeta}>{[sp.primary_vibe, sp.estimated_cost].filter(Boolean).join(" • ")}</Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </Pressable>
            ))}
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}
