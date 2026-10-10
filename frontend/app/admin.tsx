import React, { useEffect, useState } from "react";
import { Pressable, Switch, Text, TextInput, View } from "react-native";
import { useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

import { api } from "@/src/api";
import { Button, useToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

type Stats = Record<string, any>;

/** Server-enforced generation limits (app_config.limits). */
const LIMIT_FIELDS = [
  { key: "ip_hourly_cap", label: "Per network (IP) — Sparks per hour" },
  { key: "ip_daily_cap", label: "Per network (IP) — Sparks per day" },
  { key: "guest_ids_per_ip_daily", label: "New guest sessions per network per day" },
  { key: "premium_daily_cap", label: "Premium ceiling — Sparks per day" },
  { key: "premium_monthly_cap", label: "Premium ceiling — Sparks per month" },
];

/** Admin-editable feature flags (app_config.features). `id` is used in testIDs: admin-flag-<id>[-row]. */
const FLAGS = [
  { key: "experience_profiles", id: "experience-profiles", label: "Experience Profiles (Couple · Friends · Family · Celebration · Travel · Solo)" },
  { key: "experience_builder", id: "experience-builder", label: "Experience Builder (party size · exact budget · interests · when · duration · transport · Surprise me)" },
  { key: "experience_output", id: "experience-output", label: "Experience Output (itinerary travel legs · cost summary · results summary chips)" },
  { key: "venue_hours", id: "venue-hours", label: "Venue Hours (verify opening hours for the planned time · hide closed venues)" },
  { key: "real_routing", id: "real-routing", label: "Real Routing (Google Routes API travel times · requires Routes API enabled on the project · billable beyond the free tier — keep OFF until approved)" },
  { key: "server_entitlements", id: "server-entitlements", label: "Server Entitlements (Premium lane from RevenueCat webhooks + read-only lookups · requires webhook secret + API key configured and back-fill reviewed — keep OFF until rollout is approved)" },
];

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.md },
  round: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.display, fontSize: 24, fontWeight: "700", color: c.onSurface },
  body: { paddingHorizontal: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxl },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  stat: { flexBasis: "47%", flexGrow: 1, backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.lg, gap: 4 },
  statValue: { fontFamily: fonts.display, fontSize: 26, fontWeight: "700", color: c.brandPrimary },
  statLabel: { fontFamily: fonts.text, fontSize: 12, color: c.muted, fontWeight: "600" },
  section: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onSurface },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.lg, gap: spacing.md },
  listRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", minHeight: 32 },
  listLabel: { flex: 1, fontFamily: fonts.text, fontSize: 14, color: c.onSurface, fontWeight: "600" },
  listCount: { fontFamily: fonts.display, fontSize: 14, color: c.muted, fontWeight: "700" },
  label: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: c.onSurfaceTertiary },
  input: { minHeight: 48, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, fontFamily: fonts.text, fontSize: 15, color: c.onSurface, backgroundColor: c.surface },
  empty: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
}));

export default function Admin() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { isAdmin, ready } = useSession();

  const stats = useQuery({ queryKey: ["admin", "stats"], queryFn: () => api<Stats>("/admin/stats"), enabled: isAdmin });
  const config = useQuery({ queryKey: ["admin", "config"], queryFn: () => api<Stats>("/admin/config"), enabled: isAdmin });

  const [form, setForm] = useState({ free_spark_limit: "", premium_price: "", trial_days: "", promo_message: "", guidance: "", featured: "" });
  const [features, setFeatures] = useState<Record<string, boolean>>({});
  const [limits, setLimits] = useState<Record<string, string>>({});
  useEffect(() => {
    if (config.data) {
      setFeatures(config.data.features ?? {});
      setLimits(Object.fromEntries(Object.entries(config.data.limits ?? {}).map(([k, v]) => [k, String(v)])));
      setForm({
        free_spark_limit: String(config.data.free_spark_limit),
        premium_price: String(config.data.premium_price),
        trial_days: String(config.data.trial_days),
        promo_message: config.data.promo_message ?? "",
        guidance: config.data.ai_settings?.guidance ?? "",
        featured: (config.data.featured_experiences ?? []).map((f: any) => `${f.title} | ${f.tagline} | ${f.vibe}`).join("\n"),
      });
    }
  }, [config.data]);

  const save = useMutation({
    mutationFn: () =>
      api("/admin/config", {
        method: "PUT",
        json: {
          free_spark_limit: parseInt(form.free_spark_limit, 10),
          premium_price: parseFloat(form.premium_price),
          trial_days: parseInt(form.trial_days, 10),
          promo_message: form.promo_message,
          features,
          limits: Object.fromEntries(Object.entries(limits).map(([k, v]) => [k, parseInt(v, 10)]).filter(([, v]) => Number.isInteger(v) && (v as number) >= 0)),
          ai_settings: { ...(config.data?.ai_settings ?? {}), guidance: form.guidance },
          featured_experiences: form.featured
            .split("\n")
            .map((l) => l.split("|").map((x) => x.trim()))
            .filter((p) => p[0])
            .map(([title, tagline = "", vibe = ""]) => ({ title, tagline, vibe })),
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin"] });
      queryClient.invalidateQueries({ queryKey: ["config"] });
      toast.show("Settings saved ✨", "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  if (ready && !isAdmin) {
    return (
      <View style={[s.root, { alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.md }]} testID="admin-forbidden">
        <Text style={s.title}>Admins only</Text>
        <Button title="Go back" variant="secondary" testID="admin-back-forbidden" onPress={() => router.back()} />
      </View>
    );
  }

  const d = stats.data;
  const tiles: [string, string | number][] = d
    ? [
        ["Total users", d.total_users],
        ["Active (30d)", d.active_users],
        ["Sparks generated", d.sparks_generated],
        ["Sparks saved", d.sparks_saved],
        ["Sparks shared", d.sparks_shared],
        ["Sparks completed", d.sparks_completed],
        ["Premium (self-reported)", d.premium_subscribers],
        ["Trial (self-reported)", d.trial_users],
        ["MRR (self-reported)", `$${d.mrr}`],
        ["Free → Premium (self-reported)", `${d.conversion_rate}%`],
        ["Generate → Share", `${d.generate_to_share_rate}%`],
        ["Rate-limited (30d)", d.rate_limited_requests ?? 0],
      ]
    : [];

  const lists: [string, { label: string; count: number }[]][] = d
    ? [
        ["Popular relationships", d.popular_relationships],
        ["Popular vibes", d.popular_vibes],
        ["Popular locations", d.popular_locations],
        ["Most generated experiences", d.popular_experiences],
      ]
    : [];

  return (
    <View style={s.root} testID="admin-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="admin-back" style={s.round} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={s.title}>Admin dashboard</Text>
      </View>
      <KeyboardAwareScrollView contentContainerStyle={s.body} bottomOffset={40}>
        <View style={s.grid} testID="admin-stats-grid">
          {tiles.map(([l, v]) => (
            <View key={l} style={s.stat}>
              <Text style={s.statValue}>{String(v)}</Text>
              <Text style={s.statLabel}>{l}</Text>
            </View>
          ))}
        </View>
        {lists.map(([title, rows]) => (
          <View key={title} style={s.card}>
            <Text style={s.section}>{title}</Text>
            {rows?.length ? rows.map((r) => (
              <View key={r.label} style={s.listRow}>
                <Text style={s.listLabel}>{r.label}</Text>
                <Text style={s.listCount}>{r.count}</Text>
              </View>
            )) : <Text style={s.empty}>No data yet</Text>}
          </View>
        ))}

        <View style={s.card} testID="admin-config-form">
          <Text style={s.section}>Configuration</Text>
          <Text style={s.label}>Free Sparks per month</Text>
          <TextInput testID="admin-free-limit-input" style={s.input} keyboardType="number-pad" value={form.free_spark_limit} onChangeText={(v) => setForm({ ...form, free_spark_limit: v })} />
          <Text style={s.label}>Generation limits (server-enforced; X-Premium claims are ignored — the Premium lane applies only to server-verified accounts)</Text>
          {LIMIT_FIELDS.map((f) => (
            <View key={f.key} style={s.listRow}>
              <Text style={s.listLabel}>{f.label}</Text>
              <TextInput testID={`admin-limit-${f.key}`} style={[s.input, { width: 88, marginBottom: 0 }]} keyboardType="number-pad" value={limits[f.key] ?? ""} onChangeText={(v) => setLimits({ ...limits, [f.key]: v })} />
            </View>
          ))}
          <Text style={s.label}>Premium price (USD) — display only; store price is set in RevenueCat</Text>
          <TextInput testID="admin-price-input" style={s.input} keyboardType="decimal-pad" value={form.premium_price} onChangeText={(v) => setForm({ ...form, premium_price: v })} />
          <Text style={s.label}>Trial days</Text>
          <TextInput testID="admin-trial-input" style={s.input} keyboardType="number-pad" value={form.trial_days} onChangeText={(v) => setForm({ ...form, trial_days: v })} />
          <Text style={s.label}>Promotional message</Text>
          <TextInput testID="admin-promo-input" style={s.input} multiline value={form.promo_message} onChangeText={(v) => setForm({ ...form, promo_message: v })} />
          <Text style={s.label}>AI recommendation guidance</Text>
          <TextInput testID="admin-ai-input" style={s.input} multiline value={form.guidance} onChangeText={(v) => setForm({ ...form, guidance: v })} placeholder="e.g. Favor outdoor, low-cost, conversation-friendly plans" placeholderTextColor={colors.muted} />
          <Text style={s.label}>Featured experiences (one per line: Title | Tagline | Vibe)</Text>
          <TextInput testID="admin-featured-input" style={[s.input, { minHeight: 90 }]} multiline value={form.featured} onChangeText={(v) => setForm({ ...form, featured: v })} />
          <Text style={s.label}>Feature flags</Text>
          {FLAGS.map((f) => {
            const on = !!config.data && features[f.key] !== false; // never show a flag as ON before the config has loaded
            return (
              <View key={f.key} style={s.listRow}>
                <Pressable
                  style={{ flex: 1, minHeight: 44, justifyContent: "center" }}
                  testID={`admin-flag-${f.id}-row`}
                  accessibilityRole="switch"
                  accessibilityState={{ checked: on }}
                  onPress={() => setFeatures({ ...features, [f.key]: !on })}
                >
                  <Text style={s.listLabel}>{f.label}</Text>
                </Pressable>
                <Switch testID={`admin-flag-${f.id}`} value={on} onValueChange={(v) => setFeatures({ ...features, [f.key]: v })} trackColor={{ true: colors.brandPrimary, false: colors.borderStrong }} thumbColor={colors.surfaceSecondary} />
              </View>
            );
          })}
          <Button title="Save settings" testID="admin-save-button" onPress={() => save.mutate()} loading={save.isPending} />
        </View>
      </KeyboardAwareScrollView>
    </View>
  );
}
