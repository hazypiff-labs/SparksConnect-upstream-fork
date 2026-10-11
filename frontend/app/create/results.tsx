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
import { type Draft, useWizard } from "@/src/wizard";

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

  // The request is built from the draft passed to mutate(), never from a render-time closure, so "Fix" buttons
  // that change the draft and regenerate immediately send the NEW settings (audit M9).
  const scheduledFor = (d: Draft) => computeScheduledAt(d.dateLabel, d.timeLabel, d.customDate)?.toISOString() ?? null;
  const generate = useMutation({
    mutationFn: (d: Draft) =>
      api<{ sparks: Spark[]; usage: { used: number; limit: number } }>("/sparks/generate", {
        method: "POST",
        timeoutMs: 120_000, // server deadline: Places + up to two 40 s Claude attempts
        json: {
          relationship_type: d.relationship,
          vibes: d.vibes,
          budget: d.budget,
          distance: d.distance,
          location: d.location,
          exclude_titles: d.seenTitles,
          occasion: d.occasion,
          surprise: d.surprise,
          // Experience Profiles: only sent for non-Couple profiles so the original dating request is byte-for-byte unchanged
          ...(d.experienceType && d.experienceType !== "couple" ? { experience_type: d.experienceType } : {}),
          // Experience Builder: only the inputs the user actually supplied
          ...(d.surpriseMe ? { surprise_me: true } : {}),
          ...(d.partySize != null ? { party_size: d.partySize } : {}),
          ...(d.budgetAmount != null ? { budget_amount: d.budgetAmount } : {}),
          ...(d.durationHours != null ? { duration_hours: d.durationHours } : {}),
          ...(d.interests.length ? { interests: d.interests } : {}),
          ...(d.transport ? { transport: d.transport } : {}),
          ...(d.dateLabel ? { date_label: d.dateLabel === "Choose a Date" ? d.customDate || null : d.dateLabel } : {}),
          ...(d.timeLabel ? { time_label: d.timeLabel } : {}),
          ...(scheduledFor(d) ? { scheduled_at: scheduledFor(d) } : {}),
        },
      }),
    onSuccess: (data, d) => {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      update({ results: data.sparks, usage: data.usage, seenTitles: [...d.seenTitles, ...data.sparks.map((x) => x.title)] });
      queryClient.invalidateQueries({ queryKey: ["sparks"] });
    },
    onError: (err: ApiError) => {
      // A subscriber who still gets 402 has a purchase the server hasn't verified yet (webhook delay / restore needed).
      if (err.status === 402) router.push({ pathname: "/premium", params: { reason: isPremium ? "unverified" : "limit" } });
    },
  });

  useEffect(() => {
    if (!started.current && draft.results.length === 0 && draft.relationship) {
      started.current = true;
      generate.mutate(draft);
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

  const fix = (patch: Partial<Draft>) => {
    const next = { ...draft, ...patch, results: [] };
    update({ ...patch, results: [] });
    generate.mutate(next);
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
              { label: "Try Again", test: "fix-retry", action: () => generate.mutate(draft) },
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
          <Text style={s.emptyTitle}>{isPremium ? "This month’s Spark limit is reached" : "You’ve used this month’s free Sparks"}</Text>
          <Text style={s.emptySub} testID="results-limit-message">
            {isPremium
              ? "Premium allowances unlock once server-side verification is live; until then every account shares the same monthly limit. Your subscription is unaffected and it resets automatically."
              : "Go Premium for unlimited personalized experiences — free for 2 weeks."}
          </Text>
          {isPremium ? (
            <Button title="Back to Create" variant="secondary" testID="results-limit-back" onPress={() => router.replace("/create")} style={{ alignSelf: "stretch" }} />
          ) : (
            <Button title="Take Your Spark Further ✨" testID="results-premium-button" onPress={() => router.push({ pathname: "/premium", params: { reason: "limit" } })} style={{ alignSelf: "stretch" }} />
          )}
        </View>
      ) : (
        <>
          <ScrollView contentContainerStyle={s.list} showsVerticalScrollIndicator={false}>
            {draft.results.map((sp, i) => (
              <SparkCard key={sp.id} spark={sp} index={i} glance={output} hoursWarning={hours} onView={() => router.push(`/spark/${sp.id}`)} />
            ))}
          </ScrollView>
          <StickyFooter>
            <Button title="Give Me Different Ideas" variant="secondary" testID="different-ideas-button" onPress={() => generate.mutate(draft)} icon={<Ionicons name="refresh" size={18} color={colors.onBrandTertiary} />} />
          </StickyFooter>
        </>
      )}
    </View>
  );
}
