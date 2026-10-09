import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, Text, View, type PressableProps, type StyleProp, type ViewStyle } from "react-native";
import * as Haptics from "expo-haptics";
import Animated, { Easing, FadeInDown, FadeOutUp, useAnimatedStyle, useSharedValue, withRepeat, withSequence, withTiming } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";

import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

// ------------------------------------------------------------------ Spark glyph
export function SparkGlyph({ size = 28, animated = true }: { size?: number; animated?: boolean }) {
  const scale = useSharedValue(1);
  const rotate = useSharedValue(0);
  useEffect(() => {
    if (!animated) return;
    scale.value = withRepeat(withSequence(withTiming(1.18, { duration: 900, easing: Easing.inOut(Easing.ease) }), withTiming(1, { duration: 900, easing: Easing.inOut(Easing.ease) })), -1, true);
    rotate.value = withRepeat(withSequence(withTiming(-8, { duration: 1400 }), withTiming(8, { duration: 1400 })), -1, true);
  }, [animated, scale, rotate]);
  const style = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }, { rotate: `${rotate.value}deg` }] }));
  return (
    <Animated.Text style={[{ fontSize: size, lineHeight: size * 1.25 }, style]} testID="spark-glyph">
      ✨
    </Animated.Text>
  );
}

// ------------------------------------------------------------------ Button
type ButtonProps = PressableProps & {
  title: string;
  variant?: "primary" | "secondary" | "ghost" | "glass" | "inverse";
  loading?: boolean;
  icon?: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  testID: string;
};

const useButtonStyles = makeStyles((c) => ({
  base: { minHeight: 56, borderRadius: radius.pill, paddingHorizontal: spacing.xl, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: spacing.sm },
  primary: { backgroundColor: c.brandPrimary, shadowColor: c.brandPrimary, shadowOpacity: 0.35, shadowRadius: 14, shadowOffset: { width: 0, height: 8 }, elevation: 6 },
  secondary: { backgroundColor: c.brandTertiary },
  ghost: { backgroundColor: c.transparent },
  glass: { backgroundColor: c.glass, borderWidth: 1, borderColor: c.glassBorder },
  inverse: { backgroundColor: c.surfaceInverse },
  text: { fontFamily: fonts.display, fontSize: 17, fontWeight: "700", letterSpacing: 0.2 },
  tPrimary: { color: c.onBrandPrimary },
  tSecondary: { color: c.onBrandTertiary },
  tGhost: { color: c.muted },
  tGlass: { color: c.onSurfaceInverse },
  tInverse: { color: c.onSurfaceInverse },
  disabled: { opacity: 0.5 },
}));

export function Button({ title, variant = "primary", loading, icon, style, disabled, onPress, testID, ...rest }: ButtonProps) {
  const s = useButtonStyles();
  const { colors } = useTheme();
  const scale = useSharedValue(1);
  const anim = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));
  const textStyle = { primary: s.tPrimary, secondary: s.tSecondary, ghost: s.tGhost, glass: s.tGlass, inverse: s.tInverse }[variant];
  const spinnerColor = variant === "primary" || variant === "inverse" || variant === "glass" ? colors.onBrandPrimary : colors.brandPrimary;
  return (
    <Animated.View style={[anim, style]}>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        disabled={disabled || loading}
        onPressIn={() => (scale.value = withTiming(0.97, { duration: 90 }))}
        onPressOut={() => (scale.value = withTiming(1, { duration: 120 }))}
        onPress={(e) => {
          if (variant === "primary") Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
          onPress?.(e);
        }}
        style={[s.base, s[variant], (disabled || loading) && s.disabled]}
        {...rest}
      >
        {loading ? <ActivityIndicator color={spinnerColor} /> : (
          <>
            {icon}
            <Text style={[s.text, textStyle]}>{title}</Text>
          </>
        )}
      </Pressable>
    </Animated.View>
  );
}

// ------------------------------------------------------------------ Chip
const useChipStyles = makeStyles((c) => ({
  chip: { height: 36, paddingHorizontal: spacing.lg, borderRadius: radius.pill, borderWidth: 1.5, borderColor: c.border, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center", flexShrink: 0 },
  selected: { borderColor: c.brandPrimary, backgroundColor: c.brandTertiary },
  text: { fontFamily: fonts.text, fontSize: 14, fontWeight: "600", color: c.onSurfaceTertiary },
  textSelected: { color: c.onBrandTertiary },
}));

export function Chip({ label, selected, onPress, testID }: { label: string; selected?: boolean; onPress?: () => void; testID: string }) {
  const s = useChipStyles();
  return (
    <Pressable testID={testID} accessibilityRole="button" accessibilityState={{ selected: !!selected }} onPress={onPress} style={[s.chip, selected && s.selected]}>
      <Text style={[s.text, selected && s.textSelected]}>{label}</Text>
    </Pressable>
  );
}

// ------------------------------------------------------------------ Option card
const useOptionStyles = makeStyles((c) => ({
  card: { flexBasis: "47%", flexGrow: 1, minHeight: 112, borderRadius: radius.lg, padding: spacing.lg, backgroundColor: c.surfaceSecondary, borderWidth: 2, borderColor: c.border, justifyContent: "space-between", shadowColor: c.onSurface, shadowOpacity: 0.05, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 2 },
  selected: { borderColor: c.brandPrimary, backgroundColor: c.brandTertiary },
  emoji: { fontSize: 30 },
  label: { fontFamily: fonts.display, fontSize: 17, fontWeight: "700", color: c.onSurface, marginTop: spacing.sm },
  check: { position: "absolute", top: spacing.md, right: spacing.md, width: 24, height: 24, borderRadius: 12, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
}));

export function OptionCard({ emoji, label, selected, onPress, testID, index = 0 }: { emoji?: string; label: string; selected: boolean; onPress: () => void; testID: string; index?: number }) {
  const s = useOptionStyles();
  const { colors } = useTheme();
  return (
    <Animated.View entering={FadeInDown.delay(index * 60).duration(360)} style={{ flexBasis: "47%", flexGrow: 1 }}>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        accessibilityState={{ selected }}
        onPress={() => {
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
          onPress();
        }}
        style={[s.card, selected && s.selected]}
      >
        {emoji ? <Text style={s.emoji}>{emoji}</Text> : null}
        <Text style={s.label}>{label}</Text>
        {selected ? (
          <View style={s.check}>
            <Ionicons name="checkmark" size={16} color={colors.onBrandPrimary} />
          </View>
        ) : null}
      </Pressable>
    </Animated.View>
  );
}

// ------------------------------------------------------------------ Step header
const useHeaderStyles = makeStyles((c) => ({
  wrap: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, backgroundColor: c.surface },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", height: 48 },
  back: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: c.surfaceTertiary },
  track: { height: 6, borderRadius: 3, backgroundColor: c.surfaceTertiary, flex: 1, marginHorizontal: spacing.lg, overflow: "hidden" },
  fill: { height: 6, borderRadius: 3, backgroundColor: c.brandPrimary },
  step: { fontFamily: fonts.text, fontSize: 13, color: c.muted, fontWeight: "600", minWidth: 36, textAlign: "right" },
  title: { fontFamily: fonts.display, fontSize: 30, lineHeight: 36, fontWeight: "700", color: c.onSurface, marginTop: spacing.lg },
  subtitle: { fontFamily: fonts.text, fontSize: 15, color: c.muted, marginTop: spacing.sm, lineHeight: 22 },
}));

export function StepHeader({ step, total, title, subtitle, onBack, testID }: { step: number; total: number; title: string; subtitle?: string; onBack?: () => void; testID: string }) {
  const s = useHeaderStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  return (
    <View style={[s.wrap, { paddingTop: insets.top + spacing.sm }]} testID={testID}>
      <View style={s.row}>
        {onBack || router.canGoBack() ? (
          <Pressable testID={`${testID}-back`} accessibilityRole="button" onPress={onBack ?? (() => router.back())} style={s.back}>
            <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
          </Pressable>
        ) : <View style={{ width: 44 }} />}
        <View style={s.track}>
          <View style={[s.fill, { width: `${(step / total) * 100}%` }]} />
        </View>
        <Text style={s.step}>{step}/{total}</Text>
      </View>
      <Text style={s.title}>{title}</Text>
      {subtitle ? <Text style={s.subtitle}>{subtitle}</Text> : null}
    </View>
  );
}

// ------------------------------------------------------------------ Toast
type ToastKind = "info" | "success" | "error";
type ToastCtx = { show: (message: string, kind?: ToastKind) => void };
const ToastContext = createContext<ToastCtx>({ show: () => {} });

const useToastStyles = makeStyles((c) => ({
  wrap: { position: "absolute", left: spacing.lg, right: spacing.lg, alignItems: "center" },
  toast: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderRadius: radius.lg, backgroundColor: c.surfaceInverse, shadowColor: c.onSurface, shadowOpacity: 0.2, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 8, maxWidth: 480 },
  text: { fontFamily: fonts.text, color: c.onSurfaceInverse, fontSize: 14, fontWeight: "600", flexShrink: 1 },
}));

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<{ message: string; kind: ToastKind; id: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const show = useCallback((message: string, kind: ToastKind = "info") => {
    if (timer.current) clearTimeout(timer.current);
    setToast({ message, kind, id: Date.now() });
    timer.current = setTimeout(() => setToast(null), 2800);
  }, []);
  const s = useToastStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const iconName = toast?.kind === "success" ? "checkmark-circle" : toast?.kind === "error" ? "alert-circle" : "sparkles";
  const iconColor = toast?.kind === "error" ? colors.error : toast?.kind === "success" ? colors.success : colors.brandSecondary;
  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      {toast ? (
        <View style={[s.wrap, { top: insets.top + spacing.md, pointerEvents: "none" }]}>
          <Animated.View key={toast.id} entering={FadeInDown.duration(260)} exiting={FadeOutUp.duration(200)} style={s.toast} testID="toast-message">
            <Ionicons name={iconName} size={18} color={iconColor} />
            <Text style={s.text}>{toast.message}</Text>
          </Animated.View>
        </View>
      ) : null}
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

// ------------------------------------------------------------------ Sticky footer
const useFooterStyles = makeStyles((c) => ({
  footer: { paddingHorizontal: spacing.lg, paddingTop: spacing.md, backgroundColor: c.surface, borderTopWidth: 1, borderTopColor: c.divider },
}));

export function StickyFooter({ children, extraBottom = 0 }: { children: React.ReactNode; extraBottom?: number }) {
  const s = useFooterStyles();
  const insets = useSafeAreaInsets();
  return <View style={[s.footer, { paddingBottom: Math.max(insets.bottom, spacing.lg) + extraBottom }]}>{children}</View>;
}


/** Full-screen placeholder shown while feature flags load, so a screen never renders the wrong experience UI first. */
export function FeaturesLoading({ testID }: { testID: string }) {
  const { colors } = useTheme();
  return (
    <View style={{ flex: 1, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" }} testID={testID}>
      <ActivityIndicator color={colors.brandPrimary} />
    </View>
  );
}
