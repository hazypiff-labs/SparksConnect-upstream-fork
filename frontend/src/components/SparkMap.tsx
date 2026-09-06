import React from "react";
import { StyleSheet, View } from "react-native";
import MapView, { Marker } from "react-native-maps";

import type { Activity } from "@/src/api";
import { useTheme } from "@/src/theme";

export function SparkMap({ lat, lng, activities }: { lat: number | null; lng: number | null; activities: Activity[] }) {
  const { colors } = useTheme();
  const points = activities.filter((a) => a.lat != null && a.lng != null);
  const center = points[0] ?? (lat != null && lng != null ? { lat, lng } : null);
  if (!center) return <View style={[styles.map, { backgroundColor: colors.surfaceTertiary }]} />;
  return (
    <MapView
      testID="spark-map"
      style={styles.map}
      initialRegion={{ latitude: center.lat as number, longitude: center.lng as number, latitudeDelta: 0.04, longitudeDelta: 0.04 }}
    >
      {points.map((a, i) => (
        <Marker key={i} coordinate={{ latitude: a.lat as number, longitude: a.lng as number }} title={a.activity_name} description={a.venue ?? undefined} pinColor={colors.brandPrimary} />
      ))}
    </MapView>
  );
}

const styles = StyleSheet.create({ map: { width: "100%", height: "100%" } });
