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
import { useFeatures } from "@/src/features";
import { durationLabel, transportLabel } from "@/src/plan";
import { computeScheduledAt, formatScheduled } from "@/src/schedule";
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
  chipScroller: { flexGrow: 0, backgroundColor: c.surface },
  chipRow: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingBottom: spacing.md, alignItems: "center" },
  chip: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.md, height: 32, borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  chipText: { fontFamily: fonts.text, fontSize: 13, fontWeight: "600", color: c.onSurfaceTertiary },
}));

export default function Results() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { draft, update } = useWizard();
  const { isPremium } = useSession();
  const { output, hours } = useFeatures();
  const started = useRef(false);
  const scheduled = computeScheduledAt(draft.dateLabel, draft.timeLabel, draft.customDate);
  const scheduledIso = scheduled ? scheduled.toISOString() : null;

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
          // Experience Builder: only the inputs the user actually supplied
          ...(draft.surpriseMe ? { surprise_me: true } : {}),
          ...(draft.partySize != null ? { party_size: draft.partySize } : {}),
          ...(draft.budgetAmount != null ? { budget_amount: draft.budgetAmount } : {}),
          ...(draft.durationHours != null ? { duration_hours: draft.durationHours } : {}),
          ...(draft.interests.length ? { interests: draft.interests } : {}),
          ...(draft.transport ? { transport: draft.transport } : {}),
          ...(draft.dateLabel ? { date_label: draft.dateLabel === "Choose a Date" ? draft.customDate || null : draft.dateLabel } : {}),
          ...(draft.timeLabel ? { time_label: draft.timeLabel } : {}),
          ...(scheduledIso ? { scheduled_at: scheduledIso } : {}),
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

  // Direct deep-link without a draft → back to the start (navigate from an effect, never during render).
  const noDraft = !draft.relationship;
  useEffect(() => {
    if (noDraft) router.replace("/(tabs)/create");
  }, [noDraft, router]);
  if (noDraft) return null;

  const err = generate.error as ApiError | null;
  const summary = `${draft.budgetAmount != null ? `$${draft.budgetAmount}` : labelFor(BUDGETS, draft.budget)} • ${labelFor(DISTANCES, draft.distance)} • ${draft.location?.label ?? ""}`;
  // Experience Output: compact chips for every plan detail the user actually supplied.
  const whenText = formatScheduled(scheduledIso) ?? [draft.dateLabel === "Choose a Date" ? draft.customDate : draft.dateLabel, draft.timeLabel].filter(Boolean).join(" · ");
  const chips: { key: string; icon: React.ComponentProps<typeof Ionicons>["name"]; text: string }[] = [
    { key: "budget", icon: "pricetag", text: draft.budgetAmount != null ? `$${draft.budgetAmount}` : labelFor(BUDGETS, draft.budget) },
    { key: "location", icon: "location", text: [draft.location?.label, labelFor(DISTANCES, draft.distance)].filter(Boolean).join(" · ") },
    ...(whenText ? [{ key: "when", icon: "calendar" as const, text: whenText }] : []),
    ...(draft.partySize != null ? [{ key: "party", icon: "people" as const, text: `${draft.partySize} people` }] : []),
    ...(durationLabel(draft.durationHours) ? [{ key: "duration", icon: "time" as const, text: durationLabel(draft.durationHours)! }] : []),
    ...(draft.transport ? [{ key: "transport", icon: "navigate" as const, text: transportLabel(draft.transport) }] : []),
  ];

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
          <Text style={s.title}>{draft.surprise ? "Your Surprise Sparks 🎁" : draft.surpriseMe ? "Surprise! Your Sparks 🎲" : "Your Sparks ✨"}</Text>
          {output ? null : <Text style={s.sub} numberOfLines={1}>{summary}</Text>}
        </View>
      </View>
      {output ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={s.chipScroller} testID="results-summary-chips">
          {chips.map((c) => (
            <View key={c.key} style={s.chip} testID={`results-chip-${c.key}`}>
              <Ionicons name={c.icon} size={13} color={colors.onSurfaceTertiary} />
              <Text style={s.chipText} numberOfLines={1}>{c.text}</Text>
            </View>
          ))}
        </ScrollView>
      ) : null}

      {generate.isPending ? (
        <View style={s.center} testID="results-loading">
          <SparkGlyph size={64} />
          <Text style={s.loadingTitle}>Designing your moment…</Text>
          <Text style={s.loadingSub}>Matching real places nearby with the vibe you’re after. This takes a few seconds.</Text>
          <Animated.View entering={FadeIn.delay(300)} style={s.skeleton} />
        </View>
      ) : err && err.status === 429 ? (
        <View style={s.center} testID="results-rate-limited">
          <Text style={{ fontSize: 52 }}>⏳</Text>
          <Text style={s.emptyTitle}>Taking a short breather</Text>
          <Text style={s.emptySub} testID="results-rate-limited-message">{err.message}</Text>
          <Text style={s.emptySub}>{isPremium ? "This is a temporary usage limit, not a problem with your Premium plan — your access is unchanged." : "This is a temporary usage limit. Signing in keeps your Sparks and allowance with you across devices."}</Text>
          <Button title="Back to Create" variant="secondary" testID="results-rate-limited-back" onPress={() => router.replace("/create")} style={{ alignSelf: "stretch" }} />
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
              <SparkCard key={sp.id} spark={sp} index={i} glance={output} hoursWarning={hours} onView={() => router.push(`/spark/${sp.id}`)} />
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
