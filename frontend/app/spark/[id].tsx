import React, { useState } from "react";
import { Linking, Pressable, ScrollView, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, track, type Activity, type Spark } from "@/src/api";
import { addSparkToCalendar } from "@/src/calendar";
import { SparkMap } from "@/src/components/SparkMap";
import { Timeline } from "@/src/components/Timeline";
import { Button, StickyFooter, useToast } from "@/src/components/ui";
import { OCCASIONS, labelFor } from "@/src/constants";
import { formatScheduled } from "@/src/schedule";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  mapWrap: { height: 300, backgroundColor: c.surfaceTertiary },
  topBar: { position: "absolute", left: spacing.lg, right: spacing.lg, flexDirection: "row", justifyContent: "space-between" },
  round: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center", shadowColor: c.onSurface, shadowOpacity: 0.15, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 4 },
  sheet: { marginTop: -24, borderTopLeftRadius: 28, borderTopRightRadius: 28, backgroundColor: c.surface, paddingHorizontal: spacing.lg, paddingTop: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xl },
  handle: { alignSelf: "center", width: 40, height: 5, borderRadius: 3, backgroundColor: c.borderStrong, marginBottom: spacing.sm },
  kicker: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: c.brandPrimary, letterSpacing: 1 },
  title: { fontFamily: fonts.display, fontSize: 28, lineHeight: 34, fontWeight: "700", color: c.onSurface },
  tagline: { fontFamily: fonts.text, fontSize: 16, color: c.onSurfaceTertiary },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.md, height: 34, borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  chipText: { fontFamily: fonts.text, fontSize: 13, fontWeight: "600", color: c.onSurfaceTertiary },
  sectionTitle: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onSurface },
  body: { fontFamily: fonts.text, fontSize: 15, lineHeight: 23, color: c.onSurfaceSecondary },
  why: { backgroundColor: c.brandTertiary, borderRadius: radius.lg, padding: spacing.lg, gap: 6 },
  whyTitle: { fontFamily: fonts.display, fontSize: 14, fontWeight: "700", color: c.onBrandTertiary, letterSpacing: 0.6 },
  whyText: { fontFamily: fonts.text, fontSize: 14, lineHeight: 21, color: c.onBrandTertiary },
  verify: { flexDirection: "row", gap: spacing.sm, alignItems: "center", backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.md },
  verifyText: { flex: 1, fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceTertiary, lineHeight: 19 },
  row: { flexDirection: "row", gap: spacing.md },
  when: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.md },
  whenText: { fontFamily: fonts.text, fontSize: 14, fontWeight: "700", color: c.onSurface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xl },
  centerText: { fontFamily: fonts.text, fontSize: 15, color: c.muted, textAlign: "center" },
  invite: { backgroundColor: c.surfaceInverse, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm },
  inviteTitle: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onSurfaceInverse },
  inviteText: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceInverse, opacity: 0.9 },
  mystery: { backgroundColor: c.brandTertiary, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm, borderWidth: 1, borderColor: c.brandSecondary },
  mysteryTitle: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onBrandTertiary },
  mysteryRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  mysteryText: { flex: 1, fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onBrandTertiary, fontWeight: "600" },
}));

export default function SparkDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { user } = useSession();

  const spark = useQuery({ queryKey: ["sparks", id], queryFn: () => api<Spark>(`/sparks/${id}`), enabled: !!id });

  const toggleSave = useMutation({
    mutationFn: () => api(`/sparks/${id}/save`, { method: spark.data?.saved ? "DELETE" : "POST" }),
    onSuccess: (res: { saved: boolean }) => {
      queryClient.setQueryData(["sparks", id], (old: Spark | undefined) => (old ? { ...old, saved: res.saved } : old));
      queryClient.invalidateQueries({ queryKey: ["sparks", "mine"] });
      toast.show(res.saved ? "Saved to My Sparks ✨" : "Removed from saved", res.saved ? "success" : "info");
      if (res.saved && !user) setTimeout(() => toast.show("Create an account to keep Sparks across devices", "info"), 2900);
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const complete = useMutation({
    mutationFn: () => api(`/sparks/${id}/complete`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sparks"] });
      toast.show("Moment made. Beautiful. ✨", "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const reveal = useMutation({
    mutationFn: () => api<{ revealed_steps: number; total: number }>(`/sparks/${id}/reveal`, { method: "PUT" }),
    onSuccess: (res) => {
      queryClient.setQueryData(["sparks", id], (old: Spark | undefined) => (old ? { ...old, revealed_steps: res.revealed_steps } : old));
      toast.show(res.revealed_steps >= res.total ? "Every stop revealed 🎁" : `Stop ${res.revealed_steps} unlocked 🎁`, "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const accept = useMutation({
    mutationFn: () => api(`/sparks/${id}/save`, { method: "POST" }),
    onSuccess: () => {
      queryClient.setQueryData(["sparks", id], (old: Spark | undefined) => (old ? { ...old, saved: true } : old));
      queryClient.invalidateQueries({ queryKey: ["sparks", "mine"] });
      track("spark_accepted", { spark_id: id });
      toast.show("You’re in! Saved to My Sparks 🎉", "success");
      if (!user) setTimeout(() => router.push({ pathname: "/auth", params: { mode: "signup" } }), 1200);
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const [calendarBusy, setCalendarBusy] = useState(false);
  const addToCalendar = async (sp: Spark) => {
    if (!sp.scheduled_at) return;
    setCalendarBusy(true);
    try {
      const res = await addSparkToCalendar({
        title: `${sp.emoji} ${sp.title} · Date Spark`,
        notes: sp.surprise && !sp.is_owner ? "It’s a surprise ✨ Just show up." : `${sp.tagline}\n\n${sp.activities.map((a) => `${a.start_time ?? ""} ${a.activity_name}${a.venue ? ` — ${a.venue}` : ""}`).join("\n")}`,
        location: sp.meet_place ?? sp.activities[0]?.address ?? sp.location_label,
        startsAt: new Date(sp.scheduled_at),
        isOccasion: !!sp.occasion,
      });
      if (res.status === "added") toast.show(sp.occasion ? "Added with reminders 1 day & 1 hour before 📅" : "Added to your calendar 📅", "success");
      else if (res.status === "unsupported") toast.show("Calendar reminders work on your phone — open Date Spark in the app", "info");
      else if (res.status === "blocked") toast.show("Calendar access is off. Enable it in Settings.", "error");
      else toast.show("No problem — you can add it later", "info");
      if (res.status === "blocked") Linking.openSettings();
    } catch (e: any) {
      toast.show(e?.message ?? "Couldn’t add to calendar", "error");
    } finally {
      setCalendarBusy(false);
    }
  };

  if (spark.isLoading) {
    return (
      <View style={s.center} testID="spark-detail-loading">
        <Text style={{ fontSize: 40 }}>✨</Text>
        <Text style={s.centerText}>Loading your Spark…</Text>
      </View>
    );
  }
  if (spark.isError || !spark.data) {
    return (
      <View style={s.center} testID="spark-detail-error">
        <Text style={s.centerText}>We couldn’t load this Spark.</Text>
        <Button title="Retry" variant="secondary" testID="spark-detail-retry" onPress={() => spark.refetch()} />
        <Button title="Go back" variant="ghost" testID="spark-detail-back-error" onPress={() => router.back()} />
      </View>
    );
  }
  const sp = spark.data;
  const when = formatScheduled(sp.scheduled_at) ?? [sp.date_label, sp.time_label].filter(Boolean).join(" · ");
  const isOwner = !!sp.is_owner;
  const locked = !!sp.locked_for_recipient;
  const total = sp.activities.length;
  const revealed = sp.surprise && isOwner ? Math.min(sp.revealed_steps ?? 1, total) : total;
  const visibleActivities: Activity[] = [
    ...sp.activities.slice(0, revealed),
    ...sp.activities.slice(revealed).map((_, i) => ({ activity_name: `Stop ${revealed + i + 1}`, venue: null, address: null, lat: null, lng: null, rating: null, hours: null, start_time: null, end_time: null, estimated_cost: null, external_url: null, note: null, verified: true, locked: true })),
  ];
  const mapActivities = sp.surprise && isOwner ? sp.activities.slice(0, revealed) : sp.activities;

  return (
    <View style={s.root} testID="spark-detail-screen">
      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: spacing.lg }}>
        <View style={s.mapWrap}>
          <SparkMap lat={sp.lat} lng={sp.lng} activities={locked ? [] : mapActivities} />
          <View style={[s.topBar, { top: insets.top + spacing.sm }]}>
            <Pressable testID="spark-detail-back" style={s.round} onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/home"))}>
              <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
            </Pressable>
            <Pressable testID="spark-save-button" style={s.round} onPress={() => toggleSave.mutate()} disabled={toggleSave.isPending}>
              <Ionicons name={sp.saved ? "bookmark" : "bookmark-outline"} size={20} color={sp.saved ? colors.brandPrimary : colors.onSurface} />
            </Pressable>
          </View>
        </View>

        <View style={s.sheet}>
          <View style={s.handle} />
          <View style={{ gap: 6 }}>
            <Text style={s.kicker}>{sp.surprise ? "SURPRISE SPARK 🎁" : isOwner ? "YOUR SPARK ✨" : "YOU’RE INVITED ✨"}</Text>
            <Text style={s.title} testID="spark-detail-title">{sp.emoji} {sp.title}</Text>
            {sp.tagline ? <Text style={s.tagline}>{sp.tagline}</Text> : null}
          </View>

          {!isOwner ? (
            <View style={s.invite} testID="invite-banner">
              <Text style={s.inviteTitle}>Someone wants to spend time with you ✨</Text>
              <Text style={s.inviteText}>{locked ? "They’ve planned a surprise. Say yes, show up, and enjoy the mystery." : "Here’s the plan they picked for the two of you. Tap “I’m in” to save it — no account needed."}</Text>
              <Button title={sp.saved ? "You’re in 🎉" : "I’m in! 🎉"} testID="invite-accept-button" disabled={sp.saved} loading={accept.isPending} onPress={() => accept.mutate()} />
              {!user ? (
                <Button title="Create a free account to keep it" variant="glass" testID="invite-signup-button" onPress={() => router.push({ pathname: "/auth", params: { mode: "signup" } })} />
              ) : null}
            </View>
          ) : null}

          {sp.surprise ? (
            <View style={s.mystery} testID="surprise-card">
              <Text style={s.mysteryTitle}>{locked ? "It’s a surprise 🎁" : isOwner ? "Mystery mode" : "The surprise is revealed 🎁"}</Text>
              {sp.meet_time || sp.meet_place ? (
                <View style={s.mysteryRow}>
                  <Ionicons name="location" size={16} color={colors.onBrandTertiary} />
                  <Text style={s.mysteryText} testID="surprise-meet">Meet {sp.meet_time ? `at ${sp.meet_time}` : ""}{sp.meet_place ? ` · ${sp.meet_place}` : ""}</Text>
                </View>
              ) : null}
              {sp.dress_code ? (
                <View style={s.mysteryRow}>
                  <Ionicons name="shirt" size={16} color={colors.onBrandTertiary} />
                  <Text style={s.mysteryText} testID="surprise-dress-code">Dress code: {sp.dress_code}</Text>
                </View>
              ) : null}
              {locked ? <Text style={s.mysteryText}>{when ? `The full plan unlocks at ${when}.` : "The full plan unlocks when the moment arrives."}</Text> : null}
              {isOwner && revealed < total ? (
                <Button title={`Reveal stop ${revealed + 1} of ${total} 🎁`} variant="inverse" testID="reveal-next-button" loading={reveal.isPending} onPress={() => reveal.mutate()} />
              ) : null}
            </View>
          ) : null}

          {sp.occasion ? (
            <View style={s.when} testID="spark-occasion">
              <Ionicons name="gift" size={16} color={colors.brandPrimary} />
              <Text style={s.whenText}>For: {labelFor(OCCASIONS, sp.occasion)}</Text>
            </View>
          ) : null}

          <View style={s.chips}>
            <View style={s.chip}><Ionicons name="pricetag" size={13} color={colors.onSurfaceTertiary} /><Text style={s.chipText}>{sp.estimated_cost}</Text></View>
            <View style={s.chip}><Ionicons name="time" size={13} color={colors.onSurfaceTertiary} /><Text style={s.chipText}>{sp.estimated_duration}</Text></View>
            {sp.distance_miles != null ? <View style={s.chip}><Ionicons name="navigate" size={13} color={colors.onSurfaceTertiary} /><Text style={s.chipText}>{sp.distance_miles} mi</Text></View> : null}
            <View style={s.chip}><Text style={s.chipText}>{sp.primary_vibe}</Text></View>
          </View>

          {when ? (
            <View style={s.when} testID="spark-when">
              <Ionicons name="calendar" size={16} color={colors.brandPrimary} />
              <Text style={[s.whenText, { flex: 1 }]}>{when}</Text>
              {sp.scheduled_at ? (
                <Pressable testID="add-to-calendar-button" onPress={() => addToCalendar(sp)} disabled={calendarBusy} hitSlop={8}>
                  <Text style={[s.whenText, { color: colors.brandPrimary }]}>{calendarBusy ? "Adding…" : "+ Calendar"}</Text>
                </Pressable>
              ) : null}
            </View>
          ) : null}

          {locked ? null : (
          <View style={{ gap: spacing.lg }}>
          <View style={{ gap: 6 }}>
            <Text style={s.sectionTitle}>The plan</Text>
            <Text style={s.body}>{sp.description}</Text>
            <Text style={[s.body, { color: colors.muted, fontSize: 13 }]}>
              <Ionicons name="location" size={13} color={colors.muted} /> {sp.location_label}
            </Text>
          </View>

          <View style={s.why}>
            <Text style={s.whyTitle}>WHY THIS FITS YOU</Text>
            <Text style={s.whyText}>{sp.why}</Text>
          </View>

          <Text style={s.sectionTitle}>{sp.surprise && isOwner ? `Itinerary · ${revealed}/${total} revealed` : "Suggested itinerary"}</Text>
          <Timeline activities={visibleActivities} />
          </View>
          )}

          {sp.needs_verification ? (
            <View style={s.verify} testID="spark-verify-notice">
              <Ionicons name="information-circle" size={20} color={colors.warning} />
              <Text style={s.verifyText}>Some stops don’t have confirmed venue details yet. Please verify hours and availability before you go — we never invent them.</Text>
            </View>
          ) : null}

          {isOwner ? (
          <View style={s.row}>
            <Button title={sp.saved ? "Saved" : "Save"} variant="secondary" testID="spark-save-secondary" style={{ flex: 1 }} onPress={() => toggleSave.mutate()} loading={toggleSave.isPending} icon={<Ionicons name={sp.saved ? "bookmark" : "bookmark-outline"} size={18} color={colors.onBrandTertiary} />} />
            <Button title="Try Another" variant="secondary" testID="spark-try-another" style={{ flex: 1 }} onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/create"))} />
          </View>
          ) : null}
          {sp.is_owner && sp.status === "sparked" && !sp.completed_at ? (
            <Button title="We did it! Mark complete" variant="inverse" testID="spark-complete-button" onPress={() => complete.mutate()} loading={complete.isPending} />
          ) : null}
        </View>
      </ScrollView>
      <StickyFooter>
        {isOwner ? (
          <Button
            title={sp.surprise ? "Send the Surprise 🎁" : "Spark It ✨"}
            testID="spark-it-button"
            onPress={() => {
              track("spark_viewed", { spark_id: id, action: "spark_it" });
              router.push(`/share/${id}`);
            }}
          />
        ) : (
          <Button title={sp.saved ? "Plan my own Spark ✨" : "I’m in! 🎉"} testID="invite-footer-button" loading={accept.isPending} onPress={() => (sp.saved ? router.replace("/(tabs)/create") : accept.mutate())} />
        )}
      </StickyFooter>
    </View>
  );
}
