import React from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import Ionicons from "@react-native-vector-icons/ionicons";
import Animated, { FadeInDown } from "react-native-reanimated";
import { KeyboardAwareScrollView, KeyboardStickyView } from "react-native-keyboard-controller";

import { track } from "@/src/api";
import { Button, Chip, FeaturesLoading, StepHeader, StickyFooter, useToast } from "@/src/components/ui";
import { BUDGETS, QUICK_AMOUNTS, tierForAmount } from "@/src/constants";
import { useFeatures } from "@/src/features";
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
  amountCard: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.lg, gap: spacing.md, marginTop: spacing.sm },
  amountTitle: { fontFamily: fonts.display, fontSize: 16, fontWeight: "700", color: c.onSurface },
  amountRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dollar: { fontFamily: fonts.display, fontSize: 24, fontWeight: "700", color: c.brandPrimary },
  amountInput: { flex: 1, height: 52, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.md, fontFamily: fonts.display, fontSize: 22, fontWeight: "700", color: c.onSurface, backgroundColor: c.surface },
  chipRow: { gap: spacing.sm, alignItems: "center" },
}));

export default function BudgetStep() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { draft, update } = useWizard();
  const { builder, ready } = useFeatures();
  const amountText = draft.budgetAmount != null ? String(draft.budgetAmount) : "";

  const setAmount = (text: string) => {
    const n = parseFloat(text.replace(/[^0-9.]/g, ""));
    if (!text.trim() || isNaN(n)) return update({ budgetAmount: null });
    // Keep the legacy tier in sync so the engine's budget band always matches the exact amount.
    update({ budgetAmount: Math.min(100000, n), budget: tierForAmount(n) });
  };
  const canContinue = !!draft.budget || draft.budgetAmount != null;
  const Scroller = builder ? KeyboardAwareScrollView : ScrollView;
  const Footer = builder ? KeyboardStickyView : React.Fragment;

  if (!ready) return <FeaturesLoading testID="create-budget-loading" />;

  return (
    <View style={s.root} testID="create-budget-screen">
      <StepHeader step={3} total={builder ? 5 : 4} title="What's your budget?" subtitle={draft.surpriseMe ? "Total for everyone — we’ll build the surprise around it." : "Total for everyone, all stops included."} testID="budget-header" />
      <Scroller contentContainerStyle={s.list} bottomOffset={120}>
        {BUDGETS.map((b, i) => {
          const on = draft.budget === b.key && draft.budgetAmount == null;
          return (
            <Animated.View key={b.key} entering={FadeInDown.delay(i * 60).duration(360)}>
              <Pressable
                testID={`budget-option-${b.key}`}
                accessibilityRole="radio"
                accessibilityState={{ selected: on }}
                onPress={() => {
                  Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
                  update({ budget: b.key, budgetAmount: null });
                }}
                style={[s.row, on && s.selected]}
              >
                <Text style={[s.label, on && s.labelSelected]}>{b.label}</Text>
                <View style={[s.radio, on && s.radioOn]}>{on ? <Ionicons name="checkmark" size={16} color={colors.onBrandPrimary} /> : null}</View>
              </Pressable>
            </Animated.View>
          );
        })}
        {builder ? (
          <View style={s.amountCard} testID="budget-amount-card">
            <Text style={s.amountTitle}>Or enter an exact amount</Text>
            <View style={s.amountRow}>
              <Text style={s.dollar}>$</Text>
              <TextInput testID="budget-amount-input" style={s.amountInput} keyboardType="decimal-pad" placeholder="150" placeholderTextColor={colors.muted} value={amountText} onChangeText={setAmount} returnKeyType="done" />
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ height: 56 }} testID="budget-quick-row">
              {QUICK_AMOUNTS.map((a) => (
                <Chip key={a} label={`$${a}`} selected={draft.budgetAmount === a} onPress={() => setAmount(String(a))} testID={`budget-quick-${a}`} />
              ))}
            </ScrollView>
          </View>
        ) : null}
        <Text style={s.hint}>Premium unlocks advanced budget controls and multi-stop planning.</Text>
      </Scroller>
      <Footer>
      <StickyFooter>
        <Button
          title="Continue"
          testID="budget-continue-button"
          disabled={!canContinue}
          onPress={() => {
            if (!canContinue) return toast.show("Choose a budget to continue", "error");
            track("budget_selected", { budget: draft.budget, budget_amount: draft.budgetAmount });
            router.push("/create/distance");
          }}
        />
      </StickyFooter>
      </Footer>
    </View>
  );
}
