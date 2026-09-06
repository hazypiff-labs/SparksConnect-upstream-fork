import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import Ionicons from "@react-native-vector-icons/ionicons";
import Animated, { FadeInDown } from "react-native-reanimated";

import { track } from "@/src/api";
import { Button, StepHeader, StickyFooter, useToast } from "@/src/components/ui";
import { BUDGETS } from "@/src/constants";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { useWizard } from "@/src/wizard";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  list: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.xl, gap: spacing.md },
  row: { minHeight: 68, borderRadius: radius.lg, paddingHorizontal: spacing.xl, backgroundColor: c.surfaceSecondary, borderWidth: 2, borderColor: c.border, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  selected: { borderColor: c.brandPrimary, backgroundColor: c.brandTertiary },
  label: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onSurface, letterSpacing: 0.5 },
  labelSelected: { color: c.onBrandTertiary },
  radio: { width: 26, height: 26, borderRadius: 13, borderWidth: 2, borderColor: c.borderStrong, alignItems: "center", justifyContent: "center" },
  radioOn: { borderColor: c.brandPrimary, backgroundColor: c.brandPrimary },
  hint: { fontFamily: fonts.text, fontSize: 13, color: c.muted, paddingHorizontal: spacing.lg, marginTop: spacing.sm },
}));

export default function BudgetStep() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { draft, update } = useWizard();

  return (
    <View style={s.root} testID="create-budget-screen">
      <StepHeader step={3} total={4} title="What's your budget?" subtitle="Total for everyone, all stops included." testID="budget-header" />
      <ScrollView contentContainerStyle={s.list}>
        {BUDGETS.map((b, i) => {
          const on = draft.budget === b.key;
          return (
            <Animated.View key={b.key} entering={FadeInDown.delay(i * 60).duration(360)}>
              <Pressable
                testID={`budget-option-${b.key}`}
                accessibilityRole="radio"
                accessibilityState={{ selected: on }}
                onPress={() => {
                  Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
                  update({ budget: b.key });
                }}
                style={[s.row, on && s.selected]}
              >
                <Text style={[s.label, on && s.labelSelected]}>{b.label}</Text>
                <View style={[s.radio, on && s.radioOn]}>{on ? <Ionicons name="checkmark" size={16} color={colors.onBrandPrimary} /> : null}</View>
              </Pressable>
            </Animated.View>
          );
        })}
        <Text style={s.hint}>Premium unlocks advanced budget controls and multi-stop planning.</Text>
      </ScrollView>
      <StickyFooter>
        <Button
          title="Continue"
          testID="budget-continue-button"
          disabled={!draft.budget}
          onPress={() => {
            if (!draft.budget) return toast.show("Choose a budget to continue", "error");
            track("budget_selected", { budget: draft.budget });
            router.push("/create/distance");
          }}
        />
      </StickyFooter>
    </View>
  );
}
