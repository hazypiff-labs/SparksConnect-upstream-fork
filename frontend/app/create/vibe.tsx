import React, { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { track } from "@/src/api";
import { Button, Chip, OptionCard, StepHeader, StickyFooter, useToast } from "@/src/components/ui";
import { VIBES, interestsFor, profileFor } from "@/src/constants";
import { useFeatures } from "@/src/features";
import { fonts, makeStyles, spacing, useTheme } from "@/src/theme";
import { useWizard } from "@/src/wizard";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.xl },
  disclose: { marginHorizontal: spacing.lg, marginTop: -spacing.sm, flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44 },
  discloseText: { fontFamily: fonts.display, fontSize: 15, fontWeight: "700", color: c.brandPrimary },
  discloseSub: { fontFamily: fonts.text, fontSize: 13, color: c.muted, paddingHorizontal: spacing.lg, marginBottom: spacing.sm },
  chipRow: { gap: spacing.sm, paddingHorizontal: spacing.lg, alignItems: "center" },
}));

export default function VibeStep() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { draft, update } = useWizard();
  const { builder } = useFeatures();
  const [showInterests, setShowInterests] = useState(draft.interests.length > 0);
  const profileKey = profileFor(draft.experienceType).key;

  const toggle = (key: string) => update({ vibes: draft.vibes.includes(key) ? draft.vibes.filter((v) => v !== key) : [...draft.vibes, key] });
  const toggleInterest = (i: string) => update({ interests: draft.interests.includes(i) ? draft.interests.filter((x) => x !== i) : [...draft.interests, i].slice(0, 8) });

  return (
    <View style={s.root} testID="create-vibe-screen">
      <StepHeader step={2} total={builder ? 5 : 4} title="What kind of moment are you looking for?" subtitle="Choose as many as you like." testID="vibe-header" />
      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xl }}>
        <View style={s.grid}>
          {VIBES.map((v, i) => (
            <OptionCard key={v.key} index={i} emoji={v.emoji} label={v.label} selected={draft.vibes.includes(v.key)} onPress={() => toggle(v.key)} testID={`vibe-option-${v.key}`} />
          ))}
        </View>
        {builder ? (
          <>
            <Pressable testID="interests-disclose" style={s.disclose} onPress={() => setShowInterests((v) => !v)} accessibilityRole="button">
              <Ionicons name={showInterests ? "chevron-down" : "add-circle"} size={20} color={colors.brandPrimary} />
              <Text style={s.discloseText}>{showInterests ? "Interests" : "Add interests (optional)"}{draft.interests.length ? ` · ${draft.interests.length}` : ""}</Text>
            </Pressable>
            {showInterests ? (
              <View testID="interests-section">
                <Text style={s.discloseSub}>Anything you love? We’ll weave it in.</Text>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ height: 56 }} testID="interests-row">
                  {interestsFor(profileKey).map((i) => (
                    <Chip key={i} label={i} selected={draft.interests.includes(i)} onPress={() => toggleInterest(i)} testID={`interest-${i.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`} />
                  ))}
                </ScrollView>
              </View>
            ) : null}
          </>
        ) : null}
      </ScrollView>
      <StickyFooter>
        <Button
          title="Continue"
          testID="vibe-continue-button"
          disabled={draft.vibes.length === 0}
          onPress={() => {
            if (draft.vibes.length === 0) return toast.show("Pick at least one vibe", "error");
            track("vibe_selected", { vibes: draft.vibes, interests: draft.interests });
            router.push("/create/budget");
          }}
        />
      </StickyFooter>
    </View>
  );
}
