import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, track, type Spark } from "@/src/api";
import { SparkMap } from "@/src/components/SparkMap";
import { Timeline } from "@/src/components/Timeline";
import { Button, StickyFooter, useToast } from "@/src/components/ui";
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
  const when = [sp.date_label, sp.time_label].filter(Boolean).join(" · ");

  return (
    <View style={s.root} testID="spark-detail-screen">
      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: spacing.lg }}>
        <View style={s.mapWrap}>
          <SparkMap lat={sp.lat} lng={sp.lng} activities={sp.activities} />
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
            <Text style={s.kicker}>YOUR SPARK ✨</Text>
            <Text style={s.title} testID="spark-detail-title">{sp.emoji} {sp.title}</Text>
            {sp.tagline ? <Text style={s.tagline}>{sp.tagline}</Text> : null}
          </View>

          <View style={s.chips}>
            <View style={s.chip}><Ionicons name="pricetag" size={13} color={colors.onSurfaceTertiary} /><Text style={s.chipText}>{sp.estimated_cost}</Text></View>
            <View style={s.chip}><Ionicons name="time" size={13} color={colors.onSurfaceTertiary} /><Text style={s.chipText}>{sp.estimated_duration}</Text></View>
            {sp.distance_miles != null ? <View style={s.chip}><Ionicons name="navigate" size={13} color={colors.onSurfaceTertiary} /><Text style={s.chipText}>{sp.distance_miles} mi</Text></View> : null}
            <View style={s.chip}><Text style={s.chipText}>{sp.primary_vibe}</Text></View>
          </View>

          {when ? (
            <View style={s.when} testID="spark-when">
              <Ionicons name="calendar" size={16} color={colors.brandPrimary} />
              <Text style={s.whenText}>{when}</Text>
            </View>
          ) : null}

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

          <Text style={s.sectionTitle}>Suggested itinerary</Text>
          <Timeline activities={sp.activities} />

          {sp.needs_verification ? (
            <View style={s.verify} testID="spark-verify-notice">
              <Ionicons name="information-circle" size={20} color={colors.warning} />
              <Text style={s.verifyText}>Some stops don’t have confirmed venue details yet. Please verify hours and availability before you go — we never invent them.</Text>
            </View>
          ) : null}

          <View style={s.row}>
            <Button title={sp.saved ? "Saved" : "Save"} variant="secondary" testID="spark-save-secondary" style={{ flex: 1 }} onPress={() => toggleSave.mutate()} loading={toggleSave.isPending} icon={<Ionicons name={sp.saved ? "bookmark" : "bookmark-outline"} size={18} color={colors.onBrandTertiary} />} />
            <Button title="Try Another" variant="secondary" testID="spark-try-another" style={{ flex: 1 }} onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/create"))} />
          </View>
          {sp.is_owner && sp.status === "sparked" && !sp.completed_at ? (
            <Button title="We did it! Mark complete" variant="inverse" testID="spark-complete-button" onPress={() => complete.mutate()} loading={complete.isPending} />
          ) : null}
        </View>
      </ScrollView>
      <StickyFooter>
        <Button
          title="Spark It ✨"
          testID="spark-it-button"
          onPress={() => {
            track("spark_viewed", { spark_id: id, action: "spark_it" });
            router.push(`/share/${id}`);
          }}
        />
      </StickyFooter>
    </View>
  );
}
