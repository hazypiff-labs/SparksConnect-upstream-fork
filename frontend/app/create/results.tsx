import React, { useEffect, useRef } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import Ionicons from "@react-native-vector-icons/ionicons";
import Animated, { FadeIn } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, ApiError, type Spark } from "@/src/api";
import { SparkCard } from "@/src/components/SparkCard";
import { Button, SparkGlyph, StickyFooter } from "@/src/components/ui";
import { BUDGETS, DISTANCES, labelFor } from "@/src/constants";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { useWizard } from "@/src/wizard";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: c.surface },
  back: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: c.surfaceTertiary },
  title: { fontFamily: fonts.display, fontSize: 24, fontWeight: "700", color: c.onSurface },
  sub: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
  list: { paddingHorizontal: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xl },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.lg },
  loadingTitle: { fontFamily: fonts.display, fontSize: 24, fontWeight: "700", color: c.onSurface, textAlign: "center" },
  loadingSub: { fontFamily: fonts.text, fontSize: 15, color: c.muted, textAlign: "center", lineHeight: 22 },
  skeleton: { height: 200, borderRadius: radius.lg, backgroundColor: c.surfaceTertiary, width: "100%" },
  emptyTitle: { fontFamily: fonts.display, fontSize: 26, fontWeight: "700", color: c.onSurface, textAlign: "center" },
  emptySub: { fontFamily: fonts.text, fontSize: 15, color: c.muted, textAlign: "center", lineHeight: 22 },
  fixes: { width: "100%", gap: spacing.sm },
  fix: { minHeight: 56, borderRadius: radius.lg, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  fixText: { fontFamily: fonts.display, fontSize: 16, fontWeight: "700", color: c.onSurface },
}));

export default function Results() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { draft, update } = useWizard();
  const { isPremium } = useSession();
  const started = useRef(false);

  const generate = useMutation({
    mutationFn: () =>
      api<{ sparks: Spark[]; usage: { used: number; limit: number } }>("/sparks/generate", {
        method: "POST",
        json: {
          relationship_type: draft.relationship,
          vibes: draft.vibes,
          budget: draft.budget,
          distance: draft.distance,
          location: draft.location,
          exclude_titles: draft.seenTitles,
          occasion: draft.occasion,
          surprise: draft.surprise,
          // Experience Profiles: only sent for non-Couple profiles so the original dating request is byte-for-byte unchanged
          ...(draft.experienceType && draft.experienceType !== "couple" ? { experience_type: draft.experienceType } : {}),
        },
      }),
    onSuccess: (data) => {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      update({ results: data.sparks, usage: data.usage, seenTitles: [...draft.seenTitles, ...data.sparks.map((x) => x.title)] });
      queryClient.invalidateQueries({ queryKey: ["sparks"] });
    },
    onError: (err: ApiError) => {
      if (err.status === 402 && !isPremium) router.push({ pathname: "/premium", params: { reason: "limit" } });
    },
  });

  useEffect(() => {
    if (!started.current && draft.results.length === 0 && draft.relationship) {
      started.current = true;
      generate.mutate();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!draft.relationship) {
    router.replace("/(tabs)/create");
    return null;
  }

  const err = generate.error as ApiError | null;
  const summary = `${labelFor(BUDGETS, draft.budget)} • ${labelFor(DISTANCES, draft.distance)} • ${draft.location?.label ?? ""}`;

  const fix = (patch: Partial<typeof draft>) => {
    update({ ...patch, results: [] });
    setTimeout(() => generate.mutate(), 0);
  };

  return (
    <View style={s.root} testID="results-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="results-back" style={s.back} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>{draft.surprise ? "Your Surprise Sparks 🎁" : "Your Sparks ✨"}</Text>
          <Text style={s.sub} numberOfLines={1}>{summary}</Text>
        </View>
      </View>

      {generate.isPending ? (
        <View style={s.center} testID="results-loading">
          <SparkGlyph size={64} />
          <Text style={s.loadingTitle}>Designing your moment…</Text>
          <Text style={s.loadingSub}>Matching real places nearby with the vibe you’re after. This takes a few seconds.</Text>
          <Animated.View entering={FadeIn.delay(300)} style={s.skeleton} />
        </View>
      ) : err && err.status !== 402 ? (
        <ScrollView contentContainerStyle={s.center} testID="results-empty">
          <Text style={{ fontSize: 52 }}>🔍</Text>
          <Text style={s.emptyTitle}>We couldn’t find the perfect Spark yet.</Text>
          <Text style={s.emptySub}>{err.status === 404 ? "Let's widen the net a little." : err.message}</Text>
          <View style={s.fixes}>
            {[
              { label: "Expand My Search", test: "fix-expand", action: () => fix({ distance: "anywhere", vibes: [...new Set([...draft.vibes, "relaxing", "foodie"])] }) },
              { label: "Lower My Budget", test: "fix-budget", action: () => fix({ budget: draft.budget === "free" ? "free" : "under25" }) },
              { label: "Increase Distance", test: "fix-distance", action: () => fix({ distance: draft.distance === "5" ? "10" : draft.distance === "10" ? "25" : "anywhere" }) },
              { label: "Try a Different Vibe", test: "fix-vibe", action: () => router.replace("/create/vibe") },
              { label: "Try Again", test: "fix-retry", action: () => generate.mutate() },
            ].map((f) => (
              <Pressable key={f.label} testID={f.test} style={s.fix} onPress={f.action}>
                <Text style={s.fixText}>{f.label}</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </Pressable>
            ))}
          </View>
        </ScrollView>
      ) : err?.status === 402 ? (
        <View style={s.center} testID="results-limit">
          <Text style={{ fontSize: 52 }}>✨</Text>
          <Text style={s.emptyTitle}>You’ve used this month’s free Sparks</Text>
          <Text style={s.emptySub}>Go Premium for unlimited personalized experiences — free for 2 weeks.</Text>
          <Button title="Take Your Spark Further ✨" testID="results-premium-button" onPress={() => router.push({ pathname: "/premium", params: { reason: "limit" } })} style={{ alignSelf: "stretch" }} />
        </View>
      ) : (
        <>
          <ScrollView contentContainerStyle={s.list} showsVerticalScrollIndicator={false}>
            {draft.results.map((sp, i) => (
              <SparkCard key={sp.id} spark={sp} index={i} onView={() => router.push(`/spark/${sp.id}`)} />
            ))}
          </ScrollView>
          <StickyFooter>
            <Button title="Give Me Different Ideas" variant="secondary" testID="different-ideas-button" onPress={() => generate.mutate()} icon={<Ionicons name="refresh" size={18} color={colors.onBrandTertiary} />} />
          </StickyFooter>
        </>
      )}
    </View>
  );
}
