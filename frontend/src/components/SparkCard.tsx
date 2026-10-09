import React from "react";
import { Pressable, Text, View } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import Ionicons from "@react-native-vector-icons/ionicons";
import Animated, { FadeInUp } from "react-native-reanimated";

import type { Spark } from "@/src/api";
import { cardImage } from "@/src/constants";
import { glanceLine } from "@/src/plan";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { Button } from "@/src/components/ui";

const useStyles = makeStyles((c) => ({
  card: { borderRadius: radius.lg + 4, overflow: "hidden", backgroundColor: c.surfaceInverse, minHeight: 440 },
  image: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  scrim: { position: "absolute", left: 0, right: 0, bottom: 0, top: 0 },
  content: { flex: 1, justifyContent: "flex-end", padding: spacing.xl, gap: spacing.md },
  badge: { alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: c.glass, borderWidth: 1, borderColor: c.glassBorder },
  badgeText: { fontFamily: fonts.text, fontSize: 12, fontWeight: "700", color: c.onSurfaceInverse, letterSpacing: 0.4 },
  title: { fontFamily: fonts.display, fontSize: 28, lineHeight: 33, fontWeight: "700", color: c.onSurfaceInverse, letterSpacing: 0.3 },
  tagline: { fontFamily: fonts.text, fontSize: 16, color: c.onSurfaceInverse, opacity: 0.92 },
  meta: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceInverse, opacity: 0.85 },
  why: { backgroundColor: c.glass, borderColor: c.glassBorder, borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: 4 },
  whyLabel: { fontFamily: fonts.display, fontSize: 12, fontWeight: "700", color: c.onSurfaceInverse, letterSpacing: 0.6 },
  whyText: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceInverse },
  verify: { flexDirection: "row", alignItems: "center", gap: 6 },
  verifyText: { fontFamily: fonts.text, fontSize: 12, color: c.warning, fontWeight: "600" },
}));

export function SparkCard({ spark, index, onView, glance = false }: { spark: Spark; index: number; onView: () => void; glance?: boolean }) {
  const s = useStyles();
  const { colors } = useTheme();
  const meta = [spark.vibe_tags?.slice(0, 2).join(" • ") || spark.primary_vibe, spark.estimated_cost, spark.estimated_duration].filter(Boolean).join(" • ");
  const glanceText = glance ? glanceLine(spark) : null;
  return (
    <Animated.View entering={FadeInUp.delay(index * 120).duration(480)}>
      <Pressable testID={`spark-card-${index}`} onPress={onView} style={s.card}>
        <Image source={{ uri: cardImage(index) }} style={s.image} contentFit="cover" transition={300} />
        <LinearGradient colors={[colors.transparent, colors.scrimLight, colors.scrim]} locations={[0, 0.35, 1]} style={s.scrim} />
        <View style={s.content}>
          <View style={s.badge}>
            <Text style={s.badgeText}>{spark.emoji} {spark.primary_vibe?.toUpperCase()}</Text>
          </View>
          <Text style={s.title} testID={`spark-card-${index}-title`}>{spark.title}</Text>
          {spark.tagline ? <Text style={s.tagline}>{spark.tagline}</Text> : null}
          <Text style={s.meta}>{meta}</Text>
          {glanceText ? <Text style={s.meta} testID={`spark-card-${index}-glance`}>{glanceText}</Text> : null}
          <Text style={s.meta}>
            <Ionicons name="location" size={13} color={colors.onSurfaceInverse} /> {spark.distance_miles != null ? `${spark.distance_miles} miles away` : spark.location_label}
          </Text>
          <View style={s.why}>
            <Text style={s.whyLabel}>WHY WE PICKED IT</Text>
            <Text style={s.whyText} numberOfLines={3}>{spark.why}</Text>
          </View>
          {spark.needs_verification ? (
            <View style={s.verify}>
              <Ionicons name="alert-circle" size={14} color={colors.warning} />
              <Text style={s.verifyText}>Some venue details need verification</Text>
            </View>
          ) : null}
          <Button title="View Spark ✨" onPress={onView} testID={`spark-card-${index}-view`} />
        </View>
      </Pressable>
    </Animated.View>
  );
}
