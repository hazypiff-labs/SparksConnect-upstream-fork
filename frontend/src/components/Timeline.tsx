import React from "react";
import { Linking, Pressable, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import type { Activity } from "@/src/api";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  row: { flexDirection: "row", gap: spacing.md },
  timeCol: { width: 72, alignItems: "flex-end" },
  time: { fontFamily: fonts.display, fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  lineCol: { width: 24, alignItems: "center" },
  dot: { width: 14, height: 14, borderRadius: 7, backgroundColor: c.brandPrimary, borderWidth: 3, borderColor: c.brandTertiary, marginTop: 2 },
  line: { flex: 1, width: 0, borderLeftWidth: 2, borderColor: c.borderStrong, borderStyle: "dashed", marginVertical: 4 },
  card: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.lg, borderWidth: 1, borderColor: c.border, gap: 4 },
  name: { fontFamily: fonts.display, fontSize: 17, fontWeight: "700", color: c.onSurface },
  venue: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceSecondary, fontWeight: "600" },
  address: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
  note: { fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceTertiary, marginTop: 4, lineHeight: 19 },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginTop: 6 },
  meta: { fontFamily: fonts.text, fontSize: 12, color: c.muted, fontWeight: "600" },
  verify: { fontFamily: fonts.text, fontSize: 12, color: c.warning, fontWeight: "600" },
  link: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6 },
  linkText: { fontFamily: fonts.text, fontSize: 13, color: c.brandPrimary, fontWeight: "700" },
}));

export function Timeline({ activities }: { activities: Activity[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View testID="spark-itinerary">
      {activities.map((a, i) => (
        <View key={i} style={s.row} testID={`itinerary-step-${i}`}>
          <View style={s.timeCol}>
            <Text style={s.time}>{a.start_time ?? ""}</Text>
          </View>
          <View style={s.lineCol}>
            <View style={s.dot} />
            {i < activities.length - 1 ? <View style={s.line} /> : null}
          </View>
          <View style={s.card}>
            <Text style={s.name}>{a.activity_name}</Text>
            {a.venue ? <Text style={s.venue}>{a.venue}</Text> : null}
            {a.address ? <Text style={s.address}>{a.address}</Text> : null}
            {a.note ? <Text style={s.note}>{a.note}</Text> : null}
            <View style={s.metaRow}>
              {a.estimated_cost ? <Text style={s.meta}>{a.estimated_cost}</Text> : null}
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
          </View>
        </View>
      ))}
    </View>
  );
}
