import React from "react";
import { ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";

import { track } from "@/src/api";
import { Button, Chip, OptionCard, StepHeader, StickyFooter, useToast } from "@/src/components/ui";
import { OCCASIONS, RELATIONSHIPS } from "@/src/constants";
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
}));

export default function WhoStep() {
  const s = useStyles();
  const router = useRouter();
  const toast = useToast();
  const { draft, update } = useWizard();
  const { isPremium } = useSession();

  const pickOccasion = (key: string) => {
    if (draft.occasion === key) return update({ occasion: null });
    if (!isPremium) {
      track("premium_viewed", { reason: "occasion" });
      return router.push({ pathname: "/premium", params: { reason: "occasion" } });
    }
    update({ occasion: key });
  };

  return (
    <View style={s.root} testID="create-who-screen">
      <StepHeader step={1} total={4} title="Who are you spending time with?" subtitle="Pick one. We'll tailor every Spark to this connection." testID="who-header" onBack={router.canGoBack() ? () => router.back() : undefined} />
      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xl }}>
        <View style={s.grid}>
          {RELATIONSHIPS.map((r, i) => (
            <OptionCard key={r.key} index={i} emoji={r.emoji} label={r.label} selected={draft.relationship === r.key} onPress={() => update({ relationship: r.key })} testID={`who-option-${r.key}`} />
          ))}
        </View>
        <View style={s.occasionHeader}>
          <Text style={s.occasionTitle}>Planning a special occasion? {isPremium ? "" : "✨ Premium"}</Text>
          <Text style={s.occasionSub}>Optional — we’ll build a richer, multi-stop plan with occasion touches.</Text>
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
            if (!draft.relationship) return toast.show("Please select who you're with", "error");
            track("relationship_selected", { relationship_type: draft.relationship, occasion: draft.occasion });
            router.push("/create/vibe");
          }}
        />
      </StickyFooter>
    </View>
  );
}
