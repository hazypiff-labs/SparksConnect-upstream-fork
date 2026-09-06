import React, { useEffect, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type Spark } from "@/src/api";
import { Button, SparkGlyph } from "@/src/components/ui";
import { IMAGES, cardImage } from "@/src/constants";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

type Section = "saved" | "created" | "completed";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, gap: spacing.md, backgroundColor: c.surface },
  titleRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  title: { fontFamily: fonts.display, fontSize: 30, fontWeight: "700", color: c.onSurface },
  segment: { flexDirection: "row", backgroundColor: c.surfaceTertiary, borderRadius: radius.pill, padding: 4 },
  segItem: { flex: 1, height: 40, alignItems: "center", justifyContent: "center", borderRadius: radius.pill },
  segActive: { backgroundColor: c.surfaceSecondary, shadowColor: c.onSurface, shadowOpacity: 0.08, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 2 },
  segText: { fontFamily: fonts.text, fontSize: 14, fontWeight: "600", color: c.muted },
  segTextActive: { color: c.onSurface },
  row: { flexDirection: "row", gap: spacing.md, backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, padding: spacing.md, borderWidth: 1, borderColor: c.border, alignItems: "center", marginHorizontal: spacing.lg, marginBottom: spacing.md },
  thumb: { width: 84, height: 84, borderRadius: radius.md },
  rowTitle: { fontFamily: fonts.display, fontSize: 16, fontWeight: "700", color: c.onSurface },
  rowMeta: { fontFamily: fonts.text, fontSize: 13, color: c.muted, marginTop: 4 },
  rowWhen: { fontFamily: fonts.text, fontSize: 12, color: c.brandPrimary, fontWeight: "700", marginTop: 4 },
  empty: { alignItems: "center", paddingHorizontal: spacing.xl, paddingTop: spacing.xxl, gap: spacing.lg },
  emptyImg: { width: 200, height: 200, borderRadius: radius.lg },
  emptyTitle: { fontFamily: fonts.display, fontSize: 20, fontWeight: "700", color: c.onSurface, textAlign: "center" },
  emptySub: { fontFamily: fonts.text, fontSize: 14, color: c.muted, textAlign: "center", lineHeight: 20 },
  banner: { marginHorizontal: spacing.lg, marginBottom: spacing.md, backgroundColor: c.brandTertiary, borderRadius: radius.md, padding: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.sm },
  bannerText: { flex: 1, fontFamily: fonts.text, fontSize: 13, color: c.onBrandTertiary, fontWeight: "600" },
}));

export default function MySparks() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useSession();
  const [section, setSection] = useState<Section>("saved");
  const query = useQuery({ queryKey: ["sparks", "mine"], queryFn: () => api<Record<Section, Spark[]>>("/sparks/mine") });

  useEffect(() => {
    query.refetch();
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const items = query.data?.[section] ?? [];
  const emptyCopy: Record<Section, string> = {
    saved: "No sparks here yet. Go create a moment!",
    created: "Sparks you've shared or scheduled will show up here.",
    completed: "Mark a Spark complete after your moment together.",
  };

  return (
    <View style={s.root} testID="my-sparks-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.sm }]}>
        <View style={s.titleRow}>
          <Text style={s.title}>My Sparks</Text>
          <SparkGlyph size={24} />
        </View>
        <View style={s.segment} testID="my-sparks-segments">
          {(["saved", "created", "completed"] as Section[]).map((k) => (
            <Pressable key={k} testID={`segment-${k}`} onPress={() => setSection(k)} style={[s.segItem, section === k && s.segActive]}>
              <Text style={[s.segText, section === k && s.segTextActive]}>{k[0].toUpperCase() + k.slice(1)}</Text>
            </Pressable>
          ))}
        </View>
      </View>
      <ScrollView contentContainerStyle={{ paddingTop: spacing.sm, paddingBottom: spacing.xl }} refreshControl={<RefreshControl refreshing={query.isRefetching} onRefresh={() => query.refetch()} tintColor={colors.brandPrimary} />}>
        {!user && items.length > 0 ? (
          <Pressable testID="my-sparks-signup-banner" style={s.banner} onPress={() => router.push({ pathname: "/auth", params: { mode: "signup" } })}>
            <Ionicons name="cloud-upload" size={18} color={colors.onBrandTertiary} />
            <Text style={s.bannerText}>Create a free account so your Sparks follow you to any device.</Text>
            <Ionicons name="chevron-forward" size={16} color={colors.onBrandTertiary} />
          </Pressable>
        ) : null}
        {items.length === 0 ? (
          <View style={s.empty} testID="my-sparks-empty">
            <Image source={{ uri: IMAGES.empty }} style={s.emptyImg} contentFit="cover" />
            <Text style={s.emptyTitle}>{emptyCopy[section]}</Text>
            <Text style={s.emptySub}>Every great memory starts with a small plan.</Text>
            <Button title="Create a Spark ✨" testID="my-sparks-create-button" onPress={() => router.push("/(tabs)/create")} />
          </View>
        ) : (
          items.map((sp, i) => (
            <Pressable key={sp.id} testID={`my-spark-${section}-${i}`} style={s.row} onPress={() => router.push(`/spark/${sp.id}`)}>
              <Image source={{ uri: cardImage(i) }} style={s.thumb} contentFit="cover" />
              <View style={{ flex: 1 }}>
                <Text style={s.rowTitle}>{sp.emoji} {sp.title}</Text>
                <Text style={s.rowMeta} numberOfLines={1}>{[sp.primary_vibe, sp.estimated_cost, sp.estimated_duration].filter(Boolean).join(" • ")}</Text>
                {sp.date_label || sp.time_label ? <Text style={s.rowWhen}>{[sp.date_label, sp.time_label].filter(Boolean).join(" · ")}</Text> : null}
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Pressable>
          ))
        )}
      </ScrollView>
    </View>
  );
}
