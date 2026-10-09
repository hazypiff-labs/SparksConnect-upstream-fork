import React from "react";
import { Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import type { Spark } from "@/src/api";
import { costSummary, formatMiles, formatMinutes, formatMoney, transportEmoji, transportLabel } from "@/src/plan";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.lg, gap: spacing.md },
  title: { fontFamily: fonts.display, fontSize: 14, fontWeight: "700", color: c.onSurfaceTertiary, letterSpacing: 0.6 },
  figures: { flexDirection: "row", gap: spacing.lg },
  figure: { flex: 1, gap: 2 },
  value: { fontFamily: fonts.display, fontSize: 24, fontWeight: "700", color: c.onSurface },
  label: { fontFamily: fonts.text, fontSize: 12, color: c.muted, fontWeight: "600" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  rowText: { flex: 1, fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceSecondary, lineHeight: 18 },
  note: { fontFamily: fonts.text, fontSize: 12, color: c.muted, lineHeight: 17 },
  unpricedText: { flex: 1, fontFamily: fonts.text, fontSize: 13, color: c.warning, fontWeight: "600", lineHeight: 18 },
}));

/**
 * Cost + travel roll-up for one Spark. Renders nothing when there is no supporting data.
 * Totals are the sum of the plan's per-stop estimates; unpriced stops are called out, never guessed.
 */
export function CostSummary({ spark, visibleStops }: { spark: Spark; visibleStops: number }) {
  const s = useStyles();
  const { colors } = useTheme();
  const cost = costSummary(spark);
  const legs = (spark.travel_legs ?? []).filter((l) => l.to_index < visibleStops);
  const travelMinutes = legs.reduce((sum, l) => sum + l.minutes, 0);
  const travelMiles = legs.reduce((sum, l) => sum + l.miles, 0);
  const partial = visibleStops < (spark.activities?.length ?? 0);
  if (!cost && legs.length === 0) return null;

  return (
    <View style={s.card} testID="cost-summary">
      <Text style={s.title}>AT A GLANCE</Text>
      {cost ? (
        <View style={s.figures}>
          <View style={s.figure}>
            <Text style={s.value} testID="cost-total">{formatMoney(cost.total)}{cost.complete ? "" : "+"}</Text>
            <Text style={s.label}>est. total{cost.partySize ? ` · ${cost.partySize} people` : ""}</Text>
          </View>
          {cost.perPerson != null ? (
            <View style={s.figure}>
              <Text style={s.value} testID="cost-per-person">{formatMoney(cost.perPerson)}{cost.complete ? "" : "+"}</Text>
              <Text style={s.label}>est. per person</Text>
            </View>
          ) : null}
        </View>
      ) : null}
      {cost && !cost.complete ? (
        <View style={s.row} testID="cost-unpriced">
          <Ionicons name="alert-circle" size={16} color={colors.warning} />
          <Text style={s.unpricedText}>{cost.priced} of {cost.stops} stops priced — {cost.unpriced} {cost.unpriced === 1 ? "stop has" : "stops have"} no price listed, so the real total will be higher.</Text>
        </View>
      ) : cost ? (
        <View style={s.row}>
          <Ionicons name="checkmark-circle" size={16} color={colors.success} />
          <Text style={s.rowText}>All {cost.stops} stops have an estimate.</Text>
        </View>
      ) : null}
      {legs.length ? (
        <View style={s.row} testID="travel-total">
          <Text style={{ fontSize: 16 }}>{transportEmoji(legs[0].mode)}</Text>
          <Text style={s.rowText}>
            ~{formatMinutes(travelMinutes)} · {formatMiles(travelMiles)} {transportLabel(legs[0].mode).toLowerCase()} between {partial ? "revealed " : ""}stops
          </Text>
        </View>
      ) : null}
      <Text style={s.note} testID="estimate-disclaimer">
        {cost ? "Costs are estimates from the plan, not confirmed venue prices. " : ""}
        {legs.length ? "Travel is a straight-line estimate, not a road, walking or transit route." : ""}
      </Text>
    </View>
  );
}
