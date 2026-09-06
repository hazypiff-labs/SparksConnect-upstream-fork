import React from "react";
import { Linking, Pressable, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import type { Activity } from "@/src/api";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  wrap: { flex: 1, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.md },
  title: { fontFamily: fonts.display, fontSize: 16, fontWeight: "700", color: c.onSurfaceTertiary },
  sub: { fontFamily: fonts.text, fontSize: 13, color: c.muted, textAlign: "center" },
  btn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.lg, height: 40, borderRadius: radius.pill, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border },
  btnText: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: c.brandPrimary },
}));

export function SparkMap({ lat, lng, activities }: { lat: number | null; lng: number | null; activities: Activity[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const first = activities.find((a) => a.lat != null && a.lng != null);
  const clat = first?.lat ?? lat;
  const clng = first?.lng ?? lng;
  return (
    <View style={s.wrap} testID="spark-map">
      <Ionicons name="map" size={40} color={colors.brandSecondary} />
      <Text style={s.title}>Interactive map on your phone</Text>
      <Text style={s.sub}>{first?.address ?? "Open the app on iOS or Android to see the route map."}</Text>
      {clat != null && clng != null ? (
        <Pressable testID="spark-map-open" style={s.btn} onPress={() => Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${clat},${clng}`)}>
          <Ionicons name="navigate" size={14} color={colors.brandPrimary} />
          <Text style={s.btnText}>Open in Google Maps</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
