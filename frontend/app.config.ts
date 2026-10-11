import type { ConfigContext, ExpoConfig } from "expo/config";

/**
 * Build-time configuration layered over app.json (audit H7 / release hygiene). Everything store- or domain-specific
 * comes from the environment of the EAS build profile, never from the repository:
 *   IOS_BUNDLE_ID, ANDROID_PACKAGE        final store identifiers (cannot change after the first submission)
 *   IOS_BUILD_NUMBER, ANDROID_VERSION_CODE
 *   EXPO_PUBLIC_SHARE_BASE_URL            e.g. https://datespark.app → universal links / App Links for /s/<id>
 *   ANDROID_GOOGLE_MAPS_API_KEY           required by react-native-maps on Android
 */
export default ({ config }: ConfigContext): ExpoConfig => {
  const env = process.env;
  const shareHost = env.EXPO_PUBLIC_SHARE_BASE_URL ? new URL(env.EXPO_PUBLIC_SHARE_BASE_URL).host : null;
  const ios = config.ios ?? {};
  const android = config.android ?? {};
  return {
    ...config,
    name: config.name ?? "Date Spark",
    slug: config.slug ?? "date-spark",
    ios: {
      ...ios,
      bundleIdentifier: env.IOS_BUNDLE_ID ?? ios.bundleIdentifier,
      buildNumber: env.IOS_BUILD_NUMBER ?? ios.buildNumber ?? "1",
      ...(shareHost ? { associatedDomains: [`applinks:${shareHost}`] } : {}),
    },
    android: {
      ...android,
      package: env.ANDROID_PACKAGE ?? android.package,
      versionCode: env.ANDROID_VERSION_CODE ? Number(env.ANDROID_VERSION_CODE) : android.versionCode,
      ...(env.ANDROID_GOOGLE_MAPS_API_KEY ? { config: { ...android.config, googleMaps: { apiKey: env.ANDROID_GOOGLE_MAPS_API_KEY } } } : {}),
      ...(shareHost
        ? {
            intentFilters: [
              {
                action: "VIEW",
                autoVerify: true,
                data: [{ scheme: "https", host: shareHost, pathPrefix: "/s/" }],
                category: ["BROWSABLE", "DEFAULT"],
              },
            ],
          }
        : {}),
    },
  };
};
