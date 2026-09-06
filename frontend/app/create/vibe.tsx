import React from "react";
import { ScrollView, View } from "react-native";
import { useRouter } from "expo-router";

import { track } from "@/src/api";
import { Button, OptionCard, StepHeader, StickyFooter, useToast } from "@/src/components/ui";
import { VIBES } from "@/src/constants";
import { makeStyles, spacing } from "@/src/theme";
import { useWizard } from "@/src/wizard";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.xl },
}));

export default function VibeStep() {
  const s = useStyles();
  const router = useRouter();
  const toast = useToast();
  const { draft, update } = useWizard();

  const toggle = (key: string) => update({ vibes: draft.vibes.includes(key) ? draft.vibes.filter((v) => v !== key) : [...draft.vibes, key] });

  return (
    <View style={s.root} testID="create-vibe-screen">
      <StepHeader step={2} total={4} title="What kind of moment are you looking for?" subtitle="Choose as many as you like." testID="vibe-header" />
      <ScrollView contentContainerStyle={s.grid}>
        {VIBES.map((v, i) => (
          <OptionCard key={v.key} index={i} emoji={v.emoji} label={v.label} selected={draft.vibes.includes(v.key)} onPress={() => toggle(v.key)} testID={`vibe-option-${v.key}`} />
        ))}
      </ScrollView>
      <StickyFooter>
        <Button
          title="Continue"
          testID="vibe-continue-button"
          disabled={draft.vibes.length === 0}
          onPress={() => {
            if (draft.vibes.length === 0) return toast.show("Pick at least one vibe", "error");
            track("vibe_selected", { vibes: draft.vibes });
            router.push("/create/budget");
          }}
        />
      </StickyFooter>
    </View>
  );
}
