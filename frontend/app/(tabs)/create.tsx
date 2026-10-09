import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";
import Ionicons from "@react-native-vector-icons/ionicons";

import { track } from "@/src/api";
import { Button, Chip, FeaturesLoading, OptionCard, StepHeader, StickyFooter, useToast } from "@/src/components/ui";
import { EXPERIENCE_PROFILES, OCCASIONS, PARTY_DEFAULTS, profileFor, relationshipOption } from "@/src/constants";
import { useFeatures } from "@/src/features";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { useWizard } from "@/src/wizard";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  occasionHeader: { paddingHorizontal: spacing.lg, marginTop: spacing.xl, gap: 2 },
  occasionTitle: { fontFamily: fonts.display, fontSize: 17, fontWeight: "700", color: c.onSurface },
  occasionSub: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
  chipRow: { gap: spacing.sm, paddingHorizontal: spacing.lg, alignItems: "center" },
  profileLabel: { fontFamily: fonts.text, fontSize: 12, fontWeight: "700", color: c.muted, letterSpacing: 0.8, paddingHorizontal: spacing.lg, marginBottom: spacing.xs },
  soloCard: { marginHorizontal: spacing.lg, marginTop: spacing.sm, backgroundColor: c.brandTertiary, borderRadius: 20, padding: spacing.lg, gap: 4 },
  soloTitle: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onBrandTertiary },
  soloSub: { fontFamily: fonts.text, fontSize: 14, color: c.onBrandTertiary, lineHeight: 20 },
  fade: { position: "absolute", right: 0, top: 0, bottom: 0, width: 48 },
  builderRow: { marginHorizontal: spacing.lg, marginTop: spacing.lg, flexDirection: "row", gap: spacing.md },
  compact: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.md, gap: spacing.sm },
  compactLabel: { fontFamily: fonts.text, fontSize: 12, fontWeight: "700", color: c.muted, letterSpacing: 0.6 },
  stepper: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stepBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  stepVal: { fontFamily: fonts.display, fontSize: 22, fontWeight: "700", color: c.onSurface },
  surpriseMe: { flex: 1, borderRadius: radius.lg, borderWidth: 2, borderColor: c.border, backgroundColor: c.surfaceSecondary, padding: spacing.md, justifyContent: "space-between" },
  surpriseMeOn: { borderColor: c.brandPrimary, backgroundColor: c.brandTertiary },
  surpriseMeTitle: { fontFamily: fonts.display, fontSize: 15, fontWeight: "700", color: c.onSurface },
  surpriseMeSub: { fontFamily: fonts.text, fontSize: 12, color: c.muted, lineHeight: 16 },
}));

export default function WhoStep() {
  const s = useStyles();
  const router = useRouter();
  const toast = useToast();
  const { draft, update } = useWizard();
  const { isPremium } = useSession();
  const { colors } = useTheme();
  const features = useFeatures();
  // Feature flag: when off, this screen renders exactly the original Date Spark Step 1.
  const profilesEnabled = features.profiles;
  const builderEnabled = features.builder;
  const profile = profilesEnabled ? profileFor(draft.experienceType) : profileFor("couple");
  const isCouple = profile.key === "couple";
  const partySize = draft.partySize ?? PARTY_DEFAULTS[profile.key] ?? 2;

  const pickProfile = (key: string) => {
    if (key === draft.experienceType || (key === "couple" && !draft.experienceType)) return;
    const next = profileFor(key);
    const keepRelationship = draft.relationship && next.relationships?.includes(draft.relationship) ? draft.relationship : next.defaultRelationship;
    update({ experienceType: key === "couple" ? null : key, relationship: keepRelationship, partySize: null, interests: [] });
    track("experience_type_selected", { experience_type: key });
  };

  const setParty = (n: number) => update({ partySize: Math.min(50, Math.max(profile.key === "solo" ? 1 : 1, n)) });

  const pickOccasion = (key: string) => {
    if (draft.occasion === key) return update({ occasion: null });
    if (!isPremium) {
      track("premium_viewed", { reason: "occasion" });
      return router.push({ pathname: "/premium", params: { reason: "occasion" } });
    }
    update({ occasion: key });
  };

  const cards = (profile.relationships ?? []).map(relationshipOption).filter((r): r is NonNullable<typeof r> => !!r);

  // Wait for app_config before deciding which experience UI to render (no flash of Builder/Profiles UI when a flag is OFF).
  if (!features.ready) return <FeaturesLoading testID="create-who-loading" />;

  return (
    <View style={s.root} testID="create-who-screen">
      <StepHeader step={1} total={builderEnabled ? 5 : 4} title={profile.headline} subtitle={profile.subtitle} testID="who-header" onBack={router.canGoBack() ? () => router.back() : undefined} />
      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xl }}>
        {profilesEnabled ? (
          <View style={{ marginBottom: spacing.md }} testID="experience-profile-section">
            <Text style={s.profileLabel}>WHAT KIND OF EXPERIENCE?</Text>
            <View>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={[s.chipRow, { paddingRight: spacing.xxxl }]} style={{ height: 56 }} testID="experience-profile-row">
                {EXPERIENCE_PROFILES.map((p) => (
                  <Chip key={p.key} label={`${p.emoji} ${p.label}`} selected={profile.key === p.key} onPress={() => pickProfile(p.key)} testID={`profile-${p.key}`} />
                ))}
              </ScrollView>
              <LinearGradient pointerEvents="none" colors={[`${colors.surface}00`, colors.surface]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={s.fade} testID="experience-profile-fade" />
            </View>
          </View>
        ) : null}

        {builderEnabled ? (
          <View style={s.builderRow} testID="builder-quick-row">
            {!isCouple ? (
              <View style={s.compact} testID="party-size-card">
                <Text style={s.compactLabel}>{profile.key === "solo" ? "PEOPLE" : "HOW MANY PEOPLE?"}</Text>
                <View style={s.stepper}>
                  <Pressable testID="party-size-minus" style={s.stepBtn} onPress={() => setParty(partySize - 1)} disabled={partySize <= 1}>
                    <Ionicons name="remove" size={20} color={colors.onBrandTertiary} />
                  </Pressable>
                  <Text style={s.stepVal} testID="party-size-value">{partySize}</Text>
                  <Pressable testID="party-size-plus" style={s.stepBtn} onPress={() => setParty(partySize + 1)}>
                    <Ionicons name="add" size={20} color={colors.onBrandTertiary} />
                  </Pressable>
                </View>
              </View>
            ) : null}
            <Pressable
              testID="surprise-me-toggle"
              accessibilityRole="switch"
              accessibilityState={{ checked: draft.surpriseMe }}
              style={[s.surpriseMe, draft.surpriseMe && s.surpriseMeOn]}
              onPress={() => {
                const on = !draft.surpriseMe;
                update({ surpriseMe: on, ...(on ? { vibes: [], interests: [] } : {}) });
                track("surprise_me_toggled", { on });
              }}
            >
              <Text style={s.surpriseMeTitle}>🎲 Surprise me {draft.surpriseMe ? "· on" : ""}</Text>
              <Text style={s.surpriseMeSub}>{draft.surpriseMe ? "We’ll pick the vibe. Just set budget, where and when." : "Skip the vibe questions and let us choose."}</Text>
            </Pressable>
          </View>
        ) : null}

        {profile.relationships === null ? (
          <View style={s.soloCard} testID="solo-card">
            <Text style={s.soloTitle}>🧘 Just you</Text>
            <Text style={s.soloSub}>We’ll find experiences that are rewarding on your own — cafés, classes, walks, shows and more.</Text>
          </View>
        ) : (
          <View style={s.grid}>
            {cards.map((r, i) => (
              <OptionCard key={r.key} index={i} emoji={r.emoji} label={r.label} selected={draft.relationship === r.key} onPress={() => update({ relationship: r.key })} testID={`who-option-${r.key}`} />
            ))}
          </View>
        )}

        <View style={s.occasionHeader}>
          <Text style={s.occasionTitle}>{profile.key === "celebration" ? "What’s the occasion?" : "Planning a special occasion?"} {isPremium ? "" : "✨ Premium"}</Text>
          <Text style={s.occasionSub}>{profile.key === "celebration" ? "Pick the occasion for a richer, multi-stop plan with celebration touches." : "Optional — we’ll build a richer, multi-stop plan with occasion touches."}</Text>
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ height: 56, marginTop: spacing.sm }} testID="occasion-chip-row">
          {OCCASIONS.map((o) => (
            <Chip key={o.key} label={`${o.emoji} ${o.label}`} selected={draft.occasion === o.key} onPress={() => pickOccasion(o.key)} testID={`occasion-${o.key}`} />
          ))}
        </ScrollView>
      </ScrollView>
      <StickyFooter>
        <Button
          title="Continue"
          testID="who-continue-button"
          disabled={!draft.relationship}
          onPress={() => {
            if (!draft.relationship) return toast.show(isCouple ? "Please select who you're with" : "Please pick who's coming", "error");
            track("relationship_selected", { relationship_type: draft.relationship, occasion: draft.occasion, experience_type: profile.key, party_size: isCouple ? undefined : partySize, surprise_me: draft.surpriseMe });
            // Surprise me: skip the vibe questions entirely
            router.push(builderEnabled && draft.surpriseMe ? "/create/budget" : "/create/vibe");
          }}
        />
      </StickyFooter>
    </View>
  );
}
