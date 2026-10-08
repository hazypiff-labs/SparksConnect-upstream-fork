import React, { useState } from "react";
import { Linking, Pressable, Switch, Text, TextInput, View } from "react-native";
import { useRouter } from "expo-router";
import * as Location from "expo-location";
import * as Haptics from "expo-haptics";
import Ionicons from "@react-native-vector-icons/ionicons";
import { KeyboardAwareScrollView, KeyboardStickyView } from "react-native-keyboard-controller";

import { api, track } from "@/src/api";
import { Button, StepHeader, StickyFooter, useToast } from "@/src/components/ui";
import { DISTANCES, profileFor } from "@/src/constants";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { useWizard } from "@/src/wizard";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  body: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.xl, gap: spacing.md },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  opt: { flexBasis: "47%", flexGrow: 1, minHeight: 64, borderRadius: radius.lg, backgroundColor: c.surfaceSecondary, borderWidth: 2, borderColor: c.border, alignItems: "center", justifyContent: "center" },
  optOn: { borderColor: c.brandPrimary, backgroundColor: c.brandTertiary },
  optText: { fontFamily: fonts.display, fontSize: 17, fontWeight: "700", color: c.onSurface },
  optTextOn: { color: c.onBrandTertiary },
  sectionTitle: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onSurface, marginTop: spacing.lg },
  locCard: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.lg, gap: spacing.md },
  locRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  locText: { flex: 1, fontFamily: fonts.text, fontSize: 15, color: c.onSurface, fontWeight: "600" },
  locHint: { fontFamily: fonts.text, fontSize: 13, color: c.muted, lineHeight: 19 },
  inputRow: { flexDirection: "row", gap: spacing.sm },
  input: { flex: 1, height: 48, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.md, fontFamily: fonts.text, fontSize: 15, color: c.onSurface, backgroundColor: c.surface },
  smallBtn: { height: 48, paddingHorizontal: spacing.lg, borderRadius: radius.md, backgroundColor: c.surfaceInverse, alignItems: "center", justifyContent: "center" },
  smallBtnText: { fontFamily: fonts.text, fontSize: 14, fontWeight: "700", color: c.onSurfaceInverse },
  linkBtn: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", minHeight: 44 },
  linkText: { fontFamily: fonts.text, fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  surprise: { backgroundColor: c.surfaceInverse, borderRadius: radius.lg, padding: spacing.lg, flexDirection: "row", alignItems: "center", gap: spacing.md },
  surpriseTitle: { fontFamily: fonts.display, fontSize: 16, fontWeight: "700", color: c.onSurfaceInverse },
  surpriseSub: { fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceInverse, opacity: 0.85, lineHeight: 18, marginTop: 2 },
}));

export default function DistanceStep() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { draft, update } = useWizard();
  const { isPremium } = useSession();
  const [manual, setManual] = useState("");

  const toggleSurprise = (on: boolean) => {
    if (on && !isPremium) {
      track("premium_viewed", { reason: "surprise" });
      return router.push({ pathname: "/premium", params: { reason: "surprise" } });
    }
    update({ surprise: on });
  };
  const [locating, setLocating] = useState(false);
  const [geocoding, setGeocoding] = useState(false);
  const [blocked, setBlocked] = useState(false);

  const useMyLocation = async () => {
    setLocating(true);
    try {
      let perm = await Location.getForegroundPermissionsAsync();
      if (perm.status !== "granted") {
        if (!perm.canAskAgain) {
          setBlocked(true);
          toast.show("Location is off. Enter a city or ZIP instead, or open Settings.", "info");
          return;
        }
        perm = await Location.requestForegroundPermissionsAsync();
      }
      if (perm.status !== "granted") {
        if (!perm.canAskAgain) setBlocked(true);
        toast.show("No problem — enter a city or ZIP code below.", "info");
        return;
      }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      let label = "Current location";
      try {
        const [place] = await Location.reverseGeocodeAsync({ latitude: pos.coords.latitude, longitude: pos.coords.longitude });
        if (place) label = [place.city ?? place.subregion, place.region].filter(Boolean).join(", ") || label;
      } catch {}
      update({ location: { label, lat: pos.coords.latitude, lng: pos.coords.longitude } });
      track("location_selected", { method: "gps" });
    } catch {
      toast.show("Couldn't get your location. Try entering a city.", "error");
    } finally {
      setLocating(false);
    }
  };

  const useManual = async () => {
    if (!manual.trim()) return toast.show("Type a city or ZIP code", "error");
    setGeocoding(true);
    try {
      const res = await api<{ label: string; lat: number; lng: number }>(`/places/geocode?q=${encodeURIComponent(manual.trim())}`);
      update({ location: res });
      track("location_selected", { method: "manual" });
    } catch (e: any) {
      toast.show(e.message ?? "We couldn't find that place", "error");
    } finally {
      setGeocoding(false);
    }
  };

  const canContinue = !!draft.distance && !!draft.location;

  return (
    <View style={s.root} testID="create-distance-screen">
      <StepHeader step={4} total={4} title="How far are you willing to go?" subtitle="We only use your location to find nearby experiences." testID="distance-header" />
      <KeyboardAwareScrollView contentContainerStyle={s.body} bottomOffset={120}>
        <View style={s.grid}>
          {DISTANCES.map((d) => {
            const on = draft.distance === d.key;
            return (
              <Pressable
                key={d.key}
                testID={`distance-option-${d.key}`}
                accessibilityRole="radio"
                accessibilityState={{ selected: on }}
                onPress={() => {
                  Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
                  update({ distance: d.key });
                }}
                style={[s.opt, on && s.optOn]}
              >
                <Text style={[s.optText, on && s.optTextOn]}>{d.label}</Text>
              </Pressable>
            );
          })}
        </View>

        <Text style={s.sectionTitle}>{profileFor(draft.experienceType).locationTitle}</Text>
        <View style={s.locCard} testID="location-card">
          {draft.location ? (
            <View style={s.locRow}>
              <Ionicons name="location" size={20} color={colors.brandPrimary} />
              <Text style={s.locText} testID="location-label">{draft.location.label}</Text>
              <Pressable testID="location-clear" onPress={() => update({ location: null })} hitSlop={10}>
                <Ionicons name="close-circle" size={20} color={colors.muted} />
              </Pressable>
            </View>
          ) : (
            <Text style={s.locHint}>Share your location for the best nearby picks, or type a city / ZIP code.</Text>
          )}
          <Button title={draft.location ? "Update with my location" : "Use my location"} variant="secondary" loading={locating} testID="use-location-button" onPress={useMyLocation} icon={<Ionicons name="navigate" size={18} color={colors.onBrandTertiary} />} />
          {blocked ? (
            <Pressable testID="open-settings-button" style={s.linkBtn} onPress={() => Linking.openSettings()}>
              <Ionicons name="settings-outline" size={16} color={colors.brandPrimary} />
              <Text style={s.linkText}>Open Settings to enable location</Text>
            </Pressable>
          ) : null}
          <View style={s.inputRow}>
            <TextInput
              testID="location-input"
              style={s.input}
              placeholder="City or ZIP code"
              placeholderTextColor={colors.muted}
              value={manual}
              onChangeText={setManual}
              returnKeyType="search"
              onSubmitEditing={useManual}
              autoCapitalize="words"
            />
            <Pressable testID="location-search-button" style={s.smallBtn} onPress={useManual} disabled={geocoding}>
              <Text style={s.smallBtnText}>{geocoding ? "…" : "Set"}</Text>
            </Pressable>
          </View>
        </View>

        <Pressable testID="surprise-toggle-card" style={s.surprise} onPress={() => toggleSurprise(!draft.surprise)}>
          <Text style={{ fontSize: 28 }}>🎁</Text>
          <View style={{ flex: 1 }}>
            <Text style={s.surpriseTitle}>Surprise Spark {isPremium ? "" : "· Premium ✨"}</Text>
            <Text style={s.surpriseSub}>Plan a mystery date. You unlock stops one at a time; they only get the meeting point and a dress code.</Text>
          </View>
          <Switch testID="surprise-switch" value={draft.surprise} onValueChange={toggleSurprise} trackColor={{ true: colors.brandPrimary, false: colors.borderStrong }} thumbColor={colors.surfaceSecondary} />
        </Pressable>
      </KeyboardAwareScrollView>
      <KeyboardStickyView>
        <StickyFooter>
          <Button
            title="Find My Sparks ✨"
            testID="find-sparks-button"
            disabled={!canContinue}
            onPress={() => {
              if (!draft.distance) return toast.show("Choose a distance", "error");
              if (!draft.location) return toast.show("Set a starting location first", "error");
              update({ results: [], seenTitles: [] });
              router.push("/create/results");
            }}
          />
        </StickyFooter>
      </KeyboardStickyView>
    </View>
  );
}
