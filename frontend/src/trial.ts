/** Free-trial label for the paywall, derived ONLY from the store product (App Store 3.1.2, audit C3). */
export type IntroPrice = { price: number; cycles: number; periodUnit: string; periodNumberOfUnits: number } | null | undefined;

const UNIT: Record<string, string> = { DAY: "day", WEEK: "week", MONTH: "month", YEAR: "year" };

/**
 * "7-day" / "1-month" when this user is offered a free trial, else null.
 * iOS: StoreKit eligibility must be ELIGIBLE (a user who already used the trial must not be promised one).
 * Android: Google Play only returns an intro offer to eligible users, so its presence is enough.
 */
export function trialLabel(intro: IntroPrice, platform: string, iosEligible: boolean): string | null {
  if (!intro || intro.price !== 0) return null;
  if (platform === "ios" && !iosEligible) return null;
  const unit = UNIT[intro.periodUnit] ?? intro.periodUnit.toLowerCase();
  return `${intro.periodNumberOfUnits * Math.max(intro.cycles, 1)}-${unit}`;
}
