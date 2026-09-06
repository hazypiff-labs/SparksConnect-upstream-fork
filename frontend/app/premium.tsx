import React, { useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, track } from "@/src/api";
import { Button, SparkGlyph, StickyFooter, useToast } from "@/src/components/ui";
import { IMAGES, PREMIUM_FEATURES } from "@/src/constants";
import { useSubscription } from "@/src/revenuecat";
import { useSession } from "@/src/session";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  hero: { height: 300, backgroundColor: c.surfaceInverse },
  img: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  scrim: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  close: { position: "absolute", left: spacing.lg, width: 44, height: 44, borderRadius: 22, backgroundColor: c.glass, borderWidth: 1, borderColor: c.glassBorder, alignItems: "center", justifyContent: "center" },
  heroContent: { flex: 1, justifyContent: "flex-end", padding: spacing.xl, gap: spacing.sm },
  kicker: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: c.onSurfaceInverse, letterSpacing: 1.5 },
  headline: { fontFamily: fonts.display, fontSize: 34, lineHeight: 40, fontWeight: "700", color: c.onSurfaceInverse },
  body: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xl },
  title: { fontFamily: fonts.display, fontSize: 22, fontWeight: "700", color: c.onSurface },
  sub: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceTertiary },
  feature: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  featureText: { fontFamily: fonts.text, fontSize: 15, color: c.onSurface, fontWeight: "600" },
  check: { width: 26, height: 26, borderRadius: 13, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  priceCard: { backgroundColor: c.brandTertiary, borderRadius: radius.lg, padding: spacing.lg, gap: 4, borderWidth: 2, borderColor: c.brandPrimary },
  price: { fontFamily: fonts.display, fontSize: 30, fontWeight: "700", color: c.onBrandTertiary },
  priceSub: { fontFamily: fonts.text, fontSize: 14, color: c.onBrandTertiary, fontWeight: "600" },
  simulated: { fontFamily: fonts.text, fontSize: 12, color: c.muted, textAlign: "center" },
  unavailable: { backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.lg },
  unavailableText: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceTertiary, textAlign: "center", lineHeight: 20 },
  banner: { backgroundColor: c.info, borderRadius: radius.md, padding: spacing.md, flexDirection: "row", gap: spacing.sm, alignItems: "center" },
  bannerText: { flex: 1, fontFamily: fonts.text, fontSize: 13, color: c.onInfo, fontWeight: "600" },
  modalBg: { flex: 1, backgroundColor: c.scrim, justifyContent: "flex-end" },
  modalCard: { backgroundColor: c.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: spacing.xl, gap: spacing.md },
  modalTitle: { fontFamily: fonts.display, fontSize: 22, fontWeight: "700", color: c.onSurface },
  modalText: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceTertiary },
}));

export default function Premium() {
  const { reason } = useLocalSearchParams<{ reason?: string }>();
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const toast = useToast();
  const { user, identityError, isPremium } = useSession();
  const { offerings, purchase, restore, isPurchasing, isRestoring, identityReady, isLoading } = useSubscription();
  const config = useQuery({ queryKey: ["config"], queryFn: () => api("/config/public") });
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    track("premium_viewed", { reason: reason ?? "direct" });
  }, [reason]);

  const pkg = offerings?.current?.availablePackages.find((p) => p.identifier === "$rc_monthly") ?? offerings?.current?.availablePackages[0];
  const configPrice = config.data ? `$${Number(config.data.premium_price).toFixed(2)}` : "$24.99";
  const priceString = pkg && pkg.product.price > 0 ? pkg.product.priceString : configPrice;
  const trialDays = config.data?.trial_days ?? 14;

  const doPurchase = async () => {
    setConfirm(false);
    if (!pkg) return;
    try {
      track("subscription_started", { package: pkg.identifier });
      await purchase(pkg);
      toast.show("Welcome to Date Spark Premium ✨", "success");
      router.back();
    } catch (e: any) {
      if (e?.userCancelled) return;
      toast.show(e?.message === "identity_not_ready" ? "Please log in before subscribing" : e?.message ?? "Purchase failed", "error");
    }
  };

  const doRestore = async () => {
    try {
      const info = await restore();
      toast.show(info.entitlements.active.pro ? "Premium restored ✨" : "No previous purchase found", info.entitlements.active.pro ? "success" : "info");
    } catch (e: any) {
      toast.show(e?.message ?? "Restore failed", "error");
    }
  };

  const close = () => (router.canGoBack() ? router.back() : router.replace("/(tabs)/home"));

  return (
    <View style={s.root} testID="premium-screen">
      <ScrollView contentContainerStyle={{ paddingBottom: spacing.lg }} showsVerticalScrollIndicator={false}>
        <View style={s.hero}>
          <Image source={{ uri: IMAGES.welcome }} style={s.img} contentFit="cover" transition={400} />
          <LinearGradient colors={[colors.scrimLight, colors.scrim]} style={s.scrim} />
          <Pressable testID="premium-close" style={[s.close, { top: insets.top + spacing.sm }]} onPress={close}>
            <Ionicons name="close" size={22} color={colors.onSurfaceInverse} />
          </Pressable>
          <View style={s.heroContent}>
            <Text style={s.kicker}>DATE SPARK PREMIUM ✨</Text>
            <Text style={s.headline}>Make every moment count.</Text>
          </View>
        </View>
        <View style={s.body}>
          <View style={{ gap: 6 }}>
            <Text style={s.title}>Take Your Spark Further ✨</Text>
            <Text style={s.sub}>Get unlimited personalized experiences and advanced planning with Date Spark Premium.</Text>
          </View>
          {PREMIUM_FEATURES.map((f) => (
            <View key={f} style={s.feature}>
              <View style={s.check}><Ionicons name="checkmark" size={16} color={colors.onBrandTertiary} /></View>
              <Text style={s.featureText}>{f}</Text>
            </View>
          ))}
          <View style={s.priceCard} testID="premium-price-card">
            <Text style={s.price}>{priceString}/month</Text>
            <Text style={s.priceSub}>{trialDays}-day free trial for everyone. Cancel anytime.</Text>
          </View>
          {isPremium ? (
            <View style={s.banner} testID="premium-active-banner">
              <SparkGlyph size={18} animated={false} />
              <Text style={s.bannerText}>You’re already on Premium. Enjoy unlimited Sparks!</Text>
            </View>
          ) : null}
          {!user ? (
            <View style={s.banner} testID="premium-login-banner">
              <Ionicons name="person-circle" size={20} color={colors.onInfo} />
              <Text style={s.bannerText}>Log in or create an account so your subscription stays with you.</Text>
              <Pressable testID="premium-login-link" onPress={() => router.push({ pathname: "/auth", params: { mode: "signup" } })}>
                <Text style={[s.bannerText, { textDecorationLine: "underline" }]}>Go</Text>
              </Pressable>
            </View>
          ) : identityError ? (
            <View style={s.banner} testID="premium-identity-error">
              <Ionicons name="alert-circle" size={20} color={colors.onInfo} />
              <Text style={s.bannerText}>Purchase identity isn’t ready: {identityError}</Text>
            </View>
          ) : null}
          {!isLoading && !pkg ? (
            <View style={s.unavailable} testID="premium-unavailable">
              <Text style={s.unavailableText}>Subscription options are unavailable right now. Please try again later.</Text>
            </View>
          ) : null}
          {__DEV__ ? <Text style={s.simulated}>Preview mode: purchases are simulated via the RevenueCat Test Store.</Text> : null}
          <Pressable testID="premium-restore-button" onPress={doRestore} disabled={isRestoring} style={{ minHeight: 44, justifyContent: "center" }}>
            <Text style={[s.simulated, { color: colors.brandPrimary, fontWeight: "700" }]}>{isRestoring ? "Restoring…" : "Restore Purchases"}</Text>
          </Pressable>
        </View>
      </ScrollView>
      <StickyFooter>
        <View style={{ gap: spacing.sm }}>
          <Button title={isPremium ? "You're Premium ✨" : `Start Premium — ${trialDays} days free`} testID="start-premium-button" disabled={!pkg || !user || !identityReady || isPremium} loading={isPurchasing} onPress={() => setConfirm(true)} />
          <Button title="Maybe Later" variant="ghost" testID="maybe-later-button" onPress={close} />
        </View>
      </StickyFooter>

      <Modal visible={confirm} transparent animationType="slide" onRequestClose={() => setConfirm(false)}>
        <Pressable style={s.modalBg} onPress={() => setConfirm(false)}>
          <Pressable style={[s.modalCard, { paddingBottom: Math.max(insets.bottom, spacing.lg) + spacing.md }]} onPress={() => {}} testID="purchase-confirm-sheet">
            <Text style={s.modalTitle}>Start Date Spark Premium?</Text>
            <Text style={s.modalText}>{pkg?.product.title ?? "Premium Monthly"} · {priceString}/month after your {trialDays}-day free trial.{__DEV__ ? " This is a simulated Test Store purchase." : ""}</Text>
            <Button title="Confirm" testID="purchase-confirm-button" onPress={doPurchase} />
            <Button title="Cancel" variant="ghost" testID="purchase-cancel-button" onPress={() => setConfirm(false)} />
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}
