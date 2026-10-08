import React from "react";
import { ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";

import { api, track } from "@/src/api";
import { Button, Chip, OptionCard, StepHeader, StickyFooter, useToast } from "@/src/components/ui";
import { EXPERIENCE_PROFILES, OCCASIONS, profileFor, relationshipOption } from "@/src/constants";
import { useSession } from "@/src/session";
import { fonts, makeStyles, spacing } from "@/src/theme";
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
}));

export default function WhoStep() {
  const s = useStyles();
  const router = useRouter();
  const toast = useToast();
  const { draft, update } = useWizard();
  const { isPremium } = useSession();
  const config = useQuery({ queryKey: ["config"], queryFn: () => api("/config/public") });
  // Feature flag: when off, this screen renders exactly the original Date Spark Step 1.
  const profilesEnabled = config.data?.features?.experience_profiles !== false;
  const profile = profilesEnabled ? profileFor(draft.experienceType) : profileFor("couple");
  const isCouple = profile.key === "couple";

  const pickProfile = (key: string) => {
    if (key === draft.experienceType || (key === "couple" && !draft.experienceType)) return;
    const next = profileFor(key);
    const keepRelationship = draft.relationship && next.relationships?.includes(draft.relationship) ? draft.relationship : next.defaultRelationship;
    update({ experienceType: key === "couple" ? null : key, relationship: keepRelationship });
    track("experience_type_selected", { experience_type: key });
  };

  const pickOccasion = (key: string) => {
    if (draft.occasion === key) return update({ occasion: null });
    if (!isPremium) {
      track("premium_viewed", { reason: "occasion" });
      return router.push({ pathname: "/premium", params: { reason: "occasion" } });
    }
    update({ occasion: key });
  };

  const cards = (profile.relationships ?? []).map(relationshipOption).filter((r): r is NonNullable<typeof r> => !!r);

  return (
    <View style={s.root} testID="create-who-screen">
      <StepHeader step={1} total={4} title={profile.headline} subtitle={profile.subtitle} testID="who-header" onBack={router.canGoBack() ? () => router.back() : undefined} />
      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xl }}>
        {profilesEnabled ? (
          <View style={{ marginBottom: spacing.md }} testID="experience-profile-section">
            <Text style={s.profileLabel}>WHAT KIND OF EXPERIENCE?</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ height: 56 }} testID="experience-profile-row">
              {EXPERIENCE_PROFILES.map((p) => (
                <Chip key={p.key} label={`${p.emoji} ${p.label}`} selected={profile.key === p.key} onPress={() => pickProfile(p.key)} testID={`profile-${p.key}`} />
              ))}
            </ScrollView>
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
            track("relationship_selected", { relationship_type: draft.relationship, occasion: draft.occasion, experience_type: profile.key });
            router.push("/create/vibe");
          }}
        />
      </StickyFooter>
    </View>
  );
}
