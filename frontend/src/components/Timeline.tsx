import React from "react";
import { Linking, Pressable, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import type { Activity, TravelLeg } from "@/src/api";
import { formatMiles, formatMinutes, hoursBadge, stopDurationMinutes, transportEmoji, transportLabel } from "@/src/plan";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  row: { flexDirection: "row", gap: spacing.md },
  timeCol: { width: 72, alignItems: "flex-end" },
  time: { fontFamily: fonts.display, fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  lineCol: { width: 24, alignItems: "center" },
  dot: { width: 14, height: 14, borderRadius: 7, backgroundColor: c.brandPrimary, borderWidth: 3, borderColor: c.brandTertiary, marginTop: 2 },
  line: { flex: 1, width: 0, borderLeftWidth: 2, borderColor: c.borderStrong, borderStyle: "dashed", marginVertical: 4 },
  card: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.lg, borderWidth: 1, borderColor: c.border, gap: 4 },
  lockedCard: { backgroundColor: c.surfaceTertiary, borderStyle: "dashed" },
  name: { fontFamily: fonts.display, fontSize: 17, fontWeight: "700", color: c.onSurface },
  venue: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceSecondary, fontWeight: "600" },
  address: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
  note: { fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceTertiary, marginTop: 4, lineHeight: 19 },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginTop: 6 },
  meta: { fontFamily: fonts.text, fontSize: 12, color: c.muted, fontWeight: "600" },
  unpriced: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceTertiary, fontWeight: "600", fontStyle: "italic" },
  verify: { fontFamily: fonts.text, fontSize: 12, color: c.warning, fontWeight: "600" },
  link: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6 },
  linkText: { fontFamily: fonts.text, fontSize: 13, color: c.brandPrimary, fontWeight: "700" },
  // Travel connector between two stops
  travel: { flex: 1, gap: 2, marginBottom: spacing.lg, marginTop: -spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  travelText: { fontFamily: fonts.text, fontSize: 12, fontWeight: "700", color: c.onSurfaceTertiary },
  travelHint: { fontFamily: fonts.text, fontSize: 11, color: c.muted },
  // Opening-hours badge (Increment 5 · Phase 1)
  hours: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: radius.pill, marginTop: 6 },
  hoursGood: { backgroundColor: c.brandTertiary },
  hoursWarn: { backgroundColor: c.info },
  hoursNeutral: { backgroundColor: c.surfaceTertiary },
  hoursText: { fontFamily: fonts.text, fontSize: 12, fontWeight: "700" },
  hoursHint: { fontFamily: fonts.text, fontSize: 11, color: c.muted, marginTop: 2 },
}));

type Props = {
  activities: Activity[];
  /** Travel legs between consecutive stops (straight-line estimates). Omit to render the original timeline. */
  legs?: TravelLeg[];
  /** Increment 4 enrichments (durations, travel, unpriced labels). Off = original Timeline. */
  enriched?: boolean;
  /** Increment 5 · Phase 1 — show verified opening-hours badges when a stop carries `hours_status`. */
  showHours?: boolean;
};

export function Timeline({ activities, legs = [], enriched = false, showHours = false }: Props) {
  const s = useStyles();
  const { colors } = useTheme();
  const legAfter = (i: number) => legs.find((l) => l.from_index === i && l.to_index === i + 1);
  const toneStyle = { good: s.hoursGood, warn: s.hoursWarn, neutral: s.hoursNeutral } as const;
  const toneColor = { good: colors.onBrandTertiary, warn: colors.warning, neutral: colors.onSurfaceTertiary } as const;
  const toneIcon = { good: "checkmark-circle", warn: "alert-circle", neutral: "help-circle" } as const;
  return (
    <View testID="spark-itinerary">
      {activities.map((a, i) => {
        const duration = enriched && !a.locked ? stopDurationMinutes(a.start_time, a.end_time) : null;
        const leg = enriched && !a.locked && !activities[i + 1]?.locked ? legAfter(i) : undefined;
        const badge = showHours && !a.locked ? hoursBadge(a.hours_status) : null;
        return (
          <React.Fragment key={i}>
            <View style={s.row} testID={`itinerary-step-${i}`}>
              <View style={s.timeCol}>
                <Text style={s.time}>{a.locked ? "?" : a.start_time ?? ""}</Text>
                {duration != null ? <Text style={s.meta} testID={`itinerary-step-${i}-duration`}>{formatMinutes(duration)}</Text> : null}
              </View>
              <View style={s.lineCol}>
                <View style={s.dot} />
                {i < activities.length - 1 ? <View style={s.line} /> : null}
              </View>
              <View style={[s.card, a.locked && s.lockedCard]}>
                {a.locked ? (
                  <>
                    <Text style={s.name}>🔒 {a.activity_name}</Text>
                    <Text style={s.note}>Revealed when you’re ready — keep the mystery alive.</Text>
                  </>
                ) : (
                  <>
                    <Text style={s.name}>{a.activity_name}</Text>
                    {a.venue ? <Text style={s.venue}>{a.venue}</Text> : null}
                    {a.address ? <Text style={s.address}>{a.address}</Text> : null}
                    {a.note ? <Text style={s.note}>{a.note}</Text> : null}
                    {badge ? (
                      <View testID={`itinerary-step-${i}-hours`} accessibilityLabel={badge.hint ?? badge.text}>
                        <View style={[s.hours, toneStyle[badge.tone]]}>
                          <Ionicons name={toneIcon[badge.tone]} size={13} color={toneColor[badge.tone]} />
                          <Text style={[s.hoursText, { color: toneColor[badge.tone] }]} testID={`itinerary-step-${i}-hours-text`}>{badge.text}</Text>
                        </View>
                        {badge.hint && badge.hint !== badge.text ? <Text style={s.hoursHint}>{badge.hint}</Text> : null}
                      </View>
                    ) : null}
                    <View style={s.metaRow}>
                      {a.estimated_cost ? <Text style={s.meta}>{enriched ? `~${a.estimated_cost}` : a.estimated_cost}</Text> : enriched ? <Text style={s.unpriced} testID={`itinerary-step-${i}-unpriced`}>Price not listed</Text> : null}
                      {a.end_time ? <Text style={s.meta}>until {a.end_time}</Text> : null}
                      {a.rating ? <Text style={s.meta}>★ {a.rating}</Text> : null}
                      {!a.verified ? <Text style={s.verify}>Verify details</Text> : null}
                    </View>
                    {a.external_url ? (
                      <Pressable testID={`itinerary-step-${i}-maps`} style={s.link} onPress={() => Linking.openURL(a.external_url!)}>
                        <Ionicons name="map" size={14} color={colors.brandPrimary} />
                        <Text style={s.linkText}>Open in Google Maps</Text>
                      </Pressable>
                    ) : null}
                  </>
                )}
              </View>
            </View>
            {leg ? (
              <View style={s.row}>
                <View style={s.timeCol} />
                <View style={s.lineCol}>
                  <View style={[s.line, { marginTop: -spacing.lg }]} />
                </View>
                <View style={s.travel} testID={`itinerary-leg-${i}`}>
                  <Text style={s.travelText}>{transportEmoji(leg.mode)} {transportLabel(leg.mode)} ~{formatMinutes(leg.minutes)} · {formatMiles(leg.miles)}</Text>
                  <Text style={s.travelHint}>Straight-line estimate — not a road, walking or transit route</Text>
                </View>
              </View>
            ) : null}
          </React.Fragment>
        );
      })}
    </View>
  );
}
