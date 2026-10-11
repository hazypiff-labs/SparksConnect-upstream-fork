import { QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import { Text, View } from "react-native";
import { useFonts } from "expo-font";
import { StatusBar } from "expo-status-bar";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { configError } from "@/src/api";
import { ErrorBoundary } from "@/src/components/error-boundary";
import { ToastProvider } from "@/src/components/ui";
import { queryClient } from "@/src/query-client";
import { initializeRevenueCat, SubscriptionProvider } from "@/src/revenuecat";
import { SessionProvider } from "@/src/session";
import { useTheme } from "@/src/theme";
import { WizardProvider } from "@/src/wizard";

try {
  initializeRevenueCat();
} catch (err) {
  console.warn("RevenueCat unavailable:", err);
}

export default function RootLayout() {
  const { colors } = useTheme();
  const [fontsLoaded] = useFonts({
    Outfit: require("../assets/fonts/Outfit.ttf"),
    PlusJakartaSans: require("../assets/fonts/PlusJakartaSans.ttf"),
  });
  if (!fontsLoaded) return <View style={{ flex: 1, backgroundColor: colors.surface }} />;
  if (configError) {
    // A misconfigured build should say so instead of failing every request (audit N12).
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 24, backgroundColor: colors.surface }}>
        <Text style={{ color: colors.onSurface, textAlign: "center" }}>{configError}</Text>
      </View>
    );
  }
  // One app level ErrorBoundary; a render crash shows a reload screen
  // instead of a blank app.
  return (
    <ErrorBoundary>
      <GestureHandlerRootView style={{ flex: 1 }}>
        <SafeAreaProvider>
          <KeyboardProvider>
            <QueryClientProvider client={queryClient}>
              <SubscriptionProvider>
                <SessionProvider>
                  <WizardProvider>
                    <ToastProvider>
                      <StatusBar style="dark" />
                      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surface } }}>
                        <Stack.Screen name="index" />
                        <Stack.Screen name="(tabs)" />
                        <Stack.Screen name="auth" options={{ presentation: "modal" }} />
                        <Stack.Screen name="premium" options={{ presentation: "modal" }} />
                        <Stack.Screen name="forgot" options={{ presentation: "modal" }} />
                        <Stack.Screen name="verify-email" options={{ presentation: "modal" }} />
                      </Stack>
                    </ToastProvider>
                  </WizardProvider>
                </SessionProvider>
              </SubscriptionProvider>
            </QueryClientProvider>
          </KeyboardProvider>
        </SafeAreaProvider>
      </GestureHandlerRootView>
    </ErrorBoundary>
  );
}
