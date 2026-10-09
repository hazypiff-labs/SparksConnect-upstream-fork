import React from "react";
import { ScrollView, Text, TextInput, View } from "react-native";
import { useRouter } from "expo-router";
import { KeyboardAwareScrollView, KeyboardStickyView } from "react-native-keyboard-controller";

import { track } from "@/src/api";
import { Button, Chip, StepHeader, StickyFooter } from "@/src/components/ui";
import { DATE_OPTIONS, DURATIONS, TIME_OPTIONS, TRANSPORTS } from "@/src/constants";
import { computeScheduledAt, formatScheduled } from "@/src/schedule";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { useWizard } from "@/src/wizard";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  body: { paddingTop: spacing.sm, paddingBottom: spacing.xl, gap: spacing.lg },
  section: { gap: spacing.sm },
  title: { fontFamily: fonts.display, fontSize: 17, fontWeight: "700", color: c.onSurface, paddingHorizontal: spacing.lg },
  sub: { fontFamily: fonts.text, fontSize: 13, color: c.muted, paddingHorizontal: spacing.lg },
  chipRow: { gap: spacing.sm, paddingHorizontal: spacing.lg, alignItems: "center" },
  input: { marginHorizontal: spacing.lg, height: 48, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.md, fontFamily: fonts.text, fontSize: 15, color: c.onSurface, backgroundColor: c.surfaceSecondary },
  summary: { marginHorizontal: spacing.lg, backgroundColor: c.brandTertiary, borderRadius: radius.md, padding: spacing.md },
  summaryText: { fontFamily: fonts.text, fontSize: 14, fontWeight: "700", color: c.onBrandTertiary },
}));

/** Step 5 — "When & how long". Every field is optional; defaults reproduce the pre-builder behaviour. */
export default function WhenStep() {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const { draft, update } = useWizard();
  const scheduledAt = computeScheduledAt(draft.dateLabel, draft.timeLabel, draft.customDate);
  const whenText = formatScheduled(scheduledAt ? scheduledAt.toISOString() : null);

  return (
    <View style={s.root} testID="create-when-screen">
      <StepHeader step={5} total={5} title={draft.surpriseMe ? "When should the surprise happen?" : "When, and how long do you have?"} subtitle="All optional — skip anything you haven’t decided yet." testID="when-header" />
      <KeyboardAwareScrollView contentContainerStyle={s.body} bottomOffset={120}>
        <View style={s.section}>
          <Text style={s.title}>When?</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ height: 56 }} testID="when-date-row">
            {DATE_OPTIONS.map((d) => (
              <Chip key={d} label={d} selected={draft.dateLabel === d} onPress={() => update({ dateLabel: draft.dateLabel === d ? null : d })} testID={`when-date-${d.replace(/\s+/g, "-").toLowerCase()}`} />
            ))}
          </ScrollView>
          {draft.dateLabel === "Choose a Date" ? (
            <TextInput testID="when-custom-date-input" style={s.input} placeholder="e.g. June 26 or 2026-06-26" placeholderTextColor={colors.muted} value={draft.customDate} onChangeText={(v) => update({ customDate: v })} />
          ) : null}
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ height: 56 }} testID="when-time-row">
            {TIME_OPTIONS.map((t) => (
              <Chip key={t} label={t} selected={draft.timeLabel === t} onPress={() => update({ timeLabel: draft.timeLabel === t ? null : t })} testID={`when-time-${t.replace(/[:\s]/g, "").toLowerCase()}`} />
            ))}
          </ScrollView>
          {whenText ? (
            <View style={s.summary} testID="when-summary">
              <Text style={s.summaryText}>📅 {whenText} — we’ll pick places that are open then.</Text>
            </View>
          ) : null}
        </View>

        <View style={s.section}>
          <Text style={s.title}>How much time do you have?</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ height: 56 }} testID="duration-row">
            {DURATIONS.map((d) => (
              <Chip key={d.key} label={d.label} selected={draft.durationHours === d.key} onPress={() => update({ durationHours: draft.durationHours === d.key ? null : d.key })} testID={`duration-${d.key}`} />
            ))}
          </ScrollView>
        </View>

        {!draft.surpriseMe ? (
          <View style={s.section}>
            <Text style={s.title}>Getting around</Text>
            <Text style={s.sub}>We’ll space the stops to match.</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ height: 56 }} testID="transport-row">
              {TRANSPORTS.map((t) => (
                <Chip key={t.key} label={`${t.emoji} ${t.label}`} selected={draft.transport === t.key} onPress={() => update({ transport: draft.transport === t.key ? null : t.key })} testID={`transport-${t.key}`} />
              ))}
            </ScrollView>
          </View>
        ) : null}
      </KeyboardAwareScrollView>
      <KeyboardStickyView>
        <StickyFooter>
          <Button
            title="Find My Sparks ✨"
            testID="when-find-sparks-button"
            onPress={() => {
              track("location_selected", { when: draft.dateLabel, time: draft.timeLabel, duration_hours: draft.durationHours, transport: draft.transport, step: "when" });
              update({ results: [], seenTitles: [] });
              router.push("/create/results");
            }}
          />
        </StickyFooter>
      </KeyboardStickyView>
    </View>
  );
}
