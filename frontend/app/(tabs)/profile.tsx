import React, { useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Button, Chip, SparkGlyph, useToast } from "@/src/components/ui";
import { VIBES } from "@/src/constants";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.sm },
  title: { fontFamily: fonts.display, fontSize: 30, fontWeight: "700", color: c.onSurface },
  body: { paddingHorizontal: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xl },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.lg, gap: spacing.md },
  avatar: { width: 56, height: 56, borderRadius: 28, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: fonts.display, fontSize: 22, fontWeight: "700", color: c.onBrandTertiary },
  name: { fontFamily: fonts.display, fontSize: 20, fontWeight: "700", color: c.onSurface },
  meta: { fontFamily: fonts.text, fontSize: 14, color: c.muted },
  sectionTitle: { fontFamily: fonts.display, fontSize: 16, fontWeight: "700", color: c.onSurface },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 52 },
  rowText: { flex: 1, fontFamily: fonts.text, fontSize: 15, fontWeight: "600", color: c.onSurface },
  premiumCard: { backgroundColor: c.surfaceInverse, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm },
  premiumTitle: { fontFamily: fonts.display, fontSize: 18, fontWeight: "700", color: c.onSurfaceInverse },
  premiumSub: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceInverse, opacity: 0.85, lineHeight: 20 },
  badge: { alignSelf: "flex-start", paddingHorizontal: spacing.md, height: 28, borderRadius: radius.pill, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  badgeText: { fontFamily: fonts.text, fontSize: 12, fontWeight: "700", color: c.onBrandTertiary, letterSpacing: 0.5 },
  danger: { fontFamily: fonts.text, fontSize: 14, fontWeight: "700", color: c.error },
  modalBg: { flex: 1, backgroundColor: c.scrim, justifyContent: "flex-end" },
  modalCard: { backgroundColor: c.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: spacing.xl, gap: spacing.md },
  modalTitle: { fontFamily: fonts.display, fontSize: 22, fontWeight: "700", color: c.onSurface },
  modalText: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceTertiary },
}));

export default function Profile() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { user, isPremium, isAdmin, logout, deleteAccount } = useSession();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const prefs = useQuery({ queryKey: ["preferences", user?.id ?? "guest"], queryFn: () => api<{ favorite_vibes: string[] }>("/users/me/preferences") });
  const mine = useQuery({ queryKey: ["sparks", "mine"], queryFn: () => api<{ saved: unknown[]; created: unknown[]; completed: unknown[] }>("/sparks/mine") });
  const savePrefs = useMutation({
    mutationFn: (favorite_vibes: string[]) => api("/users/me/preferences", { method: "PUT", json: { ...(prefs.data ?? {}), favorite_vibes } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["preferences"] }),
  });

  const favorites = prefs.data?.favorite_vibes ?? [];
  const toggleVibe = (k: string) => savePrefs.mutate(favorites.includes(k) ? favorites.filter((v) => v !== k) : [...favorites, k]);
  const statusLabel = isAdmin ? "Admin" : isPremium ? (user?.subscription_status === "trial" ? "Premium · Trial" : "Premium") : "Free plan";

  return (
    <View style={s.root} testID="profile-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.sm }]}>
        <Text style={s.title}>Profile</Text>
        <SparkGlyph size={24} />
      </View>
      <ScrollView contentContainerStyle={s.body} showsVerticalScrollIndicator={false}>
        <View style={s.card} testID="profile-card">
          <View style={s.row}>
            <View style={s.avatar}>
              <Text style={s.avatarText}>{user ? user.name.charAt(0).toUpperCase() : "?"}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.name} testID="profile-name">{user ? user.name : "Guest"}</Text>
              <Text style={s.meta}>{user ? user.email : "Your Sparks live on this device for now"}</Text>
            </View>
          </View>
          <View style={s.badge} testID="profile-subscription-status">
            <Text style={s.badgeText}>{statusLabel.toUpperCase()}</Text>
          </View>
          {!user ? (
            <View style={{ gap: spacing.sm }}>
              <Button title="Create Account ✨" testID="profile-signup-button" onPress={() => router.push({ pathname: "/auth", params: { mode: "signup" } })} />
              <Button title="Log In" variant="secondary" testID="profile-login-button" onPress={() => router.push({ pathname: "/auth", params: { mode: "login" } })} />
            </View>
          ) : null}
        </View>

        <View style={s.card}>
          <Text style={s.sectionTitle}>Your Sparks</Text>
          <View style={{ flexDirection: "row", gap: spacing.md }}>
            {[["Saved", mine.data?.saved.length ?? 0], ["Created", mine.data?.created.length ?? 0], ["Completed", mine.data?.completed.length ?? 0]].map(([l, n]) => (
              <Pressable key={String(l)} testID={`profile-stat-${String(l).toLowerCase()}`} style={{ flex: 1, alignItems: "center", gap: 2 }} onPress={() => router.push("/(tabs)/sparks")}>
                <Text style={[s.name, { color: colors.brandPrimary }]}>{String(n)}</Text>
                <Text style={s.meta}>{String(l)}</Text>
              </Pressable>
            ))}
          </View>
        </View>

        <View style={s.card}>
          <Text style={s.sectionTitle}>Favorite vibes</Text>
          <Text style={s.meta}>We use these to personalize your Sparks.</Text>
          <View style={s.chips} testID="profile-favorite-vibes">
            {VIBES.map((v) => (
              <Chip key={v.key} label={`${v.emoji} ${v.label}`} selected={favorites.includes(v.key)} onPress={() => toggleVibe(v.key)} testID={`pref-vibe-${v.key}`} />
            ))}
          </View>
        </View>

        {!isPremium ? (
          <Pressable testID="profile-premium-card" style={s.premiumCard} onPress={() => router.push("/premium")}>
            <Text style={s.premiumTitle}>Date Spark Premium ✨</Text>
            <Text style={s.premiumSub}>Unlimited Sparks, richer itineraries, surprise mode. Free for 2 weeks.</Text>
            <Button title="Take Your Spark Further" variant="primary" testID="profile-premium-button" onPress={() => router.push("/premium")} />
          </Pressable>
        ) : null}

        {isAdmin ? (
          <Pressable testID="profile-admin-link" style={[s.card, s.row]} onPress={() => router.push("/admin")}>
            <Ionicons name="stats-chart" size={20} color={colors.brandPrimary} />
            <Text style={s.rowText}>Admin dashboard</Text>
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </Pressable>
        ) : null}

        {user ? (
          <View style={s.card}>
            <Pressable testID="profile-logout-button" style={s.row} onPress={async () => { await logout(); toast.show("Logged out", "info"); }}>
              <Ionicons name="log-out-outline" size={20} color={colors.onSurface} />
              <Text style={s.rowText}>Log out</Text>
            </Pressable>
            <Pressable testID="profile-delete-button" style={s.row} onPress={() => setConfirmDelete(true)}>
              <Ionicons name="trash-outline" size={20} color={colors.error} />
              <Text style={[s.rowText, s.danger]}>Delete account</Text>
            </Pressable>
          </View>
        ) : null}
        <Text style={[s.meta, { textAlign: "center" }]}>Date Spark ✨ · Find something. Spark a plan. Make a memory.</Text>
      </ScrollView>

      <Modal visible={confirmDelete} transparent animationType="slide" onRequestClose={() => setConfirmDelete(false)}>
        <Pressable style={s.modalBg} onPress={() => setConfirmDelete(false)}>
          <Pressable style={[s.modalCard, { paddingBottom: Math.max(insets.bottom, spacing.lg) + spacing.md }]} onPress={() => {}} testID="delete-confirm-sheet">
            <Text style={s.modalTitle}>Delete your account?</Text>
            <Text style={s.modalText}>Your profile and Sparks will be removed. This can’t be undone from the app.</Text>
            <Button title="Delete account" variant="inverse" testID="delete-confirm-button" onPress={async () => { setConfirmDelete(false); try { await deleteAccount(); toast.show("Account deleted", "info"); } catch (e: any) { toast.show(e.message, "error"); } }} />
            <Button title="Keep my account" variant="ghost" testID="delete-cancel-button" onPress={() => setConfirmDelete(false)} />
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}
