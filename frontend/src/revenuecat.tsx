import React, { createContext, useContext, useEffect } from "react";
import { Platform } from "react-native";
import Purchases, { LOG_LEVEL } from "react-native-purchases";
import type { CustomerInfo, PurchasesPackage } from "react-native-purchases";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const REVENUECAT_TEST_API_KEY = process.env.EXPO_PUBLIC_REVENUECAT_TEST_API_KEY;
const REVENUECAT_IOS_API_KEY = process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY;
const REVENUECAT_ANDROID_API_KEY = process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY;

export const REVENUECAT_ENTITLEMENT_IDENTIFIER = "pro";

/** Only the key this build actually needs is required: the Test Store key in development / web preview, the
 * platform key in a store build (a production build no longer breaks because the test key is absent — audit M8). */
function getRevenueCatApiKey(): string | undefined {
  if (__DEV__ && REVENUECAT_TEST_API_KEY) return REVENUECAT_TEST_API_KEY;
  if (Platform.OS === "ios") return REVENUECAT_IOS_API_KEY;
  if (Platform.OS === "android") return REVENUECAT_ANDROID_API_KEY;
  return __DEV__ ? REVENUECAT_TEST_API_KEY : undefined;
}

export const rcEnabled = (Platform.OS !== "web" || __DEV__) && !!getRevenueCatApiKey();
/** True when purchases go to RevenueCat's Test Store (simulated) rather than the real store. */
export const rcUsingTestStore = rcEnabled && getRevenueCatApiKey() === REVENUECAT_TEST_API_KEY;

export function initializeRevenueCat() {
  if (!rcEnabled) {
    if (__DEV__) console.warn("RevenueCat disabled: no API key for this platform/build");
    return;
  }
  Purchases.setLogLevel(__DEV__ ? LOG_LEVEL.DEBUG : LOG_LEVEL.WARN);
  Purchases.configure({ apiKey: getRevenueCatApiKey()! });
}

function useSubscriptionContext() {
  const queryClient = useQueryClient();

  const customerInfoQuery = useQuery({
    queryKey: ["revenuecat", "customer-info"],
    queryFn: () => Purchases.getCustomerInfo(),
    enabled: rcEnabled,
    staleTime: 60 * 1000,
  });

  const offeringsQuery = useQuery({
    queryKey: ["revenuecat", "offerings"],
    queryFn: () => Purchases.getOfferings(),
    enabled: rcEnabled,
    staleTime: 300 * 1000,
  });

  useEffect(() => {
    if (!rcEnabled) return;
    const listener = (info: CustomerInfo) => queryClient.setQueryData(["revenuecat", "customer-info"], info);
    Purchases.addCustomerInfoUpdateListener(listener);
    return () => {
      Purchases.removeCustomerInfoUpdateListener(listener);
    };
  }, [queryClient]);

  const purchaseMutation = useMutation({
    mutationFn: async (packageToPurchase: PurchasesPackage) => {
      // The CURRENT app user id must be our backend user (Purchases.logIn), or the server can't attribute the purchase.
      if (await Purchases.isAnonymous()) throw new Error("identity_not_ready");
      const { customerInfo } = await Purchases.purchasePackage(packageToPurchase);
      return customerInfo;
    },
  });

  const restoreMutation = useMutation({
    mutationFn: async () => {
      // Restoring onto an anonymous RevenueCat id would attach the purchase to nobody the server knows (audit M8).
      if (await Purchases.isAnonymous()) throw new Error("identity_not_ready");
      return Purchases.restorePurchases();
    },
  });

  const entitlement = customerInfoQuery.data?.entitlements.active?.[REVENUECAT_ENTITLEMENT_IDENTIFIER];
  const isSubscribed = entitlement !== undefined;
  const isTrial = entitlement?.periodType === "TRIAL";
  // Re-evaluated whenever customer info changes (the session stores the logIn() result there).
  const anonymousQuery = useQuery({
    queryKey: ["revenuecat", "is-anonymous", customerInfoQuery.dataUpdatedAt],
    queryFn: () => Purchases.isAnonymous(),
    enabled: rcEnabled,
  });
  const identityReady = anonymousQuery.data === false;

  return {
    customerInfo: customerInfoQuery.data,
    offerings: offeringsQuery.data,
    isSubscribed,
    isTrial,
    expirationDate: entitlement?.expirationDate ?? null,
    managementURL: customerInfoQuery.data?.managementURL ?? null,
    identityReady,
    isLoading: customerInfoQuery.isLoading || offeringsQuery.isLoading,
    purchase: purchaseMutation.mutateAsync,
    restore: restoreMutation.mutateAsync,
    isPurchasing: purchaseMutation.isPending,
    isRestoring: restoreMutation.isPending,
  };
}

type SubscriptionContextValue = ReturnType<typeof useSubscriptionContext>;
const Context = createContext<SubscriptionContextValue | null>(null);

export function SubscriptionProvider({ children }: { children: React.ReactNode }) {
  const value = useSubscriptionContext();
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSubscription() {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useSubscription must be used within a SubscriptionProvider");
  return ctx;
}
