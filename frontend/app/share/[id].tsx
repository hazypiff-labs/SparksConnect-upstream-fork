import React, { useState } from "react";
import { Pressable, ScrollView, Share, Text, TextInput, View } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import Ionicons from "@react-native-vector-icons/ionicons";
import Animated, { FadeInUp } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

import { api, type Spark } from "@/src/api";
import { Button, Chip, SparkGlyph, StickyFooter, useToast } from "@/src/components/ui";
import { DATE_OPTIONS, IMAGES, TIME_OPTIONS } from "@/src/constants";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.brandTertiary },
  header: { paddingHorizontal: spacing.lg, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: spacing.md },
  round: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onBrandTertiary, letterSpacing: 1 },
  body: { paddingHorizontal: spacing.lg, gap: spacing.xl, paddingBottom: spacing.xl },
  card: { borderRadius: radius.lg + 4, overflow: "hidden", backgroundColor: c.surfaceInverse, minHeight: 320, shadowColor: c.onSurface, shadowOpacity: 0.25, shadowRadius: 20, shadowOffset: { width: 0, height: 12 }, elevation: 10 },
  img: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  scrim: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  cardContent: { flex: 1, padding: spacing.xl, justifyContent: "flex-end", gap: spacing.sm },
  found: { fontFamily: fonts.display, fontSize: 26, lineHeight: 32, fontWeight: "700", color: c.onSurfaceInverse },
  cardTitle: { fontFamily: fonts.display, fontSize: 20, fontWeight: "700", color: c.onSurfaceInverse, marginTop: spacing.sm },
  cardMeta: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceInverse, opacity: 0.9 },
  quote: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceInverse, fontStyle: "italic", marginTop: spacing.sm },
  section: { gap: spacing.md },
  sectionTitle: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onSurface },
  chipRow: { gap: spacing.sm, paddingRight: spacing.lg },
  input: { height: 48, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.md, fontFamily: fonts.text, fontSize: 15, color: c.onSurface, backgroundColor: c.surfaceSecondary },
  hint: { fontFamily: fonts.text, fontSize: 13, color: c.muted, lineHeight: 19 },
  row: { flexDirection: "row", gap: spacing.md },
}));

export default function SparkIt() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();

  const spark = useQuery({ queryKey: ["sparks", id], queryFn: () => api<Spark>(`/sparks/${id}`), enabled: !!id });
  const [dateChoice, setDateChoice] = useState<string | null>(spark.data?.date_label ?? null);
  const [customDate, setCustomDate] = useState("");
  const [time, setTime] = useState<string | null>(spark.data?.time_label ?? null);

  const dateLabel = dateChoice === "Choose a Date" ? customDate.trim() || null : dateChoice;

  const share = useMutation({
    mutationFn: (mode: "share" | "copy") =>
      api<{ invitation: string; when: string }>(`/sparks/${id}/share`, { method: "POST", json: { date_label: dateLabel, time_label: time } }).then((r) => ({ ...r, mode })),
    onSuccess: async ({ invitation, mode }) => {
      queryClient.invalidateQueries({ queryKey: ["sparks"] });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      if (mode === "copy") {
        await Clipboard.setStringAsync(invitation);
        toast.show("Invitation copied ✨", "success");
        return;
      }
      try {
        await Share.share({ message: invitation, title: "I found something for us ✨" });
      } catch {
        await Clipboard.setStringAsync(invitation);
        toast.show("Sharing isn't available here — invitation copied instead", "info");
      }
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const sp = spark.data;
  const when = [dateLabel, time].filter(Boolean).join(" · ");

  return (
    <View style={s.root} testID="spark-it-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="spark-it-back" style={s.round} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={s.headerTitle}>SPARK IT</Text>
        <SparkGlyph size={24} />
      </View>
      <KeyboardAwareScrollView contentContainerStyle={s.body} bottomOffset={160} showsVerticalScrollIndicator={false}>
        <Animated.View entering={FadeInUp.duration(500)} style={s.card} testID="invitation-card">
          <Image source={{ uri: IMAGES.share }} style={s.img} contentFit="cover" transition={400} />
          <LinearGradient colors={[colors.scrimLight, colors.scrimLight, colors.scrim]} locations={[0, 0.3, 1]} style={s.scrim} />
          <View style={s.cardContent}>
            <Text style={s.found}>I found something for us. ✨</Text>
            {sp ? (
              <>
                <Text style={s.cardTitle} testID="invitation-title">{sp.emoji} {sp.title}</Text>
                {sp.tagline ? <Text style={s.cardMeta}>{sp.tagline}</Text> : null}
                {when ? <Text style={s.cardMeta} testID="invitation-when">📅 {when}</Text> : null}
                <Text style={s.cardMeta}>📍 {sp.location_label}</Text>
              </>
            ) : null}
            <Text style={s.quote}>“I found something I think we’d enjoy. Want to come with me?”</Text>
          </View>
        </Animated.View>

        <View style={s.section}>
          <Text style={s.sectionTitle}>When? (optional)</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ height: 56 }}>
            {DATE_OPTIONS.map((d) => (
              <Chip key={d} label={d} selected={dateChoice === d} onPress={() => setDateChoice(dateChoice === d ? null : d)} testID={`date-option-${d.replace(/\s+/g, "-").toLowerCase()}`} />
            ))}
          </ScrollView>
          {dateChoice === "Choose a Date" ? (
            <TextInput testID="custom-date-input" style={s.input} placeholder="e.g. Friday, June 26" placeholderTextColor={colors.muted} value={customDate} onChangeText={setCustomDate} />
          ) : null}
          <Text style={s.sectionTitle}>Choose a time</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ height: 56 }}>
            {TIME_OPTIONS.map((t) => (
              <Chip key={t} label={t} selected={time === t} onPress={() => setTime(time === t ? null : t)} testID={`time-option-${t.replace(/[:\s]/g, "").toLowerCase()}`} />
            ))}
          </ScrollView>
          <Text style={s.hint}>Venue hours shown in the itinerary come from the venue’s listing — we never invent availability.</Text>
        </View>
      </KeyboardAwareScrollView>
      <StickyFooter>
        <View style={{ gap: spacing.sm }}>
          <Button title="Share Spark" testID="share-spark-button" onPress={() => share.mutate("share")} loading={share.isPending && share.variables === "share"} icon={<Ionicons name="share-social" size={18} color={colors.onBrandPrimary} />} />
          <Button title="Copy Invitation" variant="secondary" testID="copy-invitation-button" onPress={() => share.mutate("copy")} loading={share.isPending && share.variables === "copy"} icon={<Ionicons name="copy" size={18} color={colors.onBrandTertiary} />} />
        </View>
      </StickyFooter>
    </View>
  );
}
