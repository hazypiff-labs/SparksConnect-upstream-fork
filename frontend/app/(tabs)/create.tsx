import React from "react";
import { ScrollView, View } from "react-native";
import { useRouter } from "expo-router";

import { track } from "@/src/api";
import { Button, OptionCard, StepHeader, StickyFooter, useToast } from "@/src/components/ui";
import { RELATIONSHIPS } from "@/src/constants";
import { makeStyles, spacing } from "@/src/theme";
import { useWizard } from "@/src/wizard";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.xl },
}));

export default function WhoStep() {
  const s = useStyles();
  const router = useRouter();
  const toast = useToast();
  const { draft, update } = useWizard();

  return (
    <View style={s.root} testID="create-who-screen">
      <StepHeader step={1} total={4} title="Who are you spending time with?" subtitle="Pick one. We'll tailor every Spark to this connection." testID="who-header" onBack={router.canGoBack() ? () => router.back() : undefined} />
      <ScrollView contentContainerStyle={s.grid}>
        {RELATIONSHIPS.map((r, i) => (
          <OptionCard key={r.key} index={i} emoji={r.emoji} label={r.label} selected={draft.relationship === r.key} onPress={() => update({ relationship: r.key })} testID={`who-option-${r.key}`} />
        ))}
      </ScrollView>
      <StickyFooter>
        <Button
          title="Continue"
          testID="who-continue-button"
          disabled={!draft.relationship}
          onPress={() => {
            if (!draft.relationship) return toast.show("Please select who you're with", "error");
            track("relationship_selected", { relationship_type: draft.relationship });
            router.push("/create/vibe");
          }}
        />
      </StickyFooter>
    </View>
  );
}
