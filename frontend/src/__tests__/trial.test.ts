/// <reference types="jest" />
import { trialLabel } from "@/src/trial";

const week = { price: 0, cycles: 1, periodUnit: "WEEK", periodNumberOfUnits: 1 };

test("no intro offer or a paid intro → no free-trial promise", () => {
  expect(trialLabel(null, "ios", true)).toBeNull();
  expect(trialLabel({ ...week, price: 0.99 }, "android", true)).toBeNull();
});

test("iOS only promises a trial to StoreKit-eligible users", () => {
  expect(trialLabel(week, "ios", false)).toBeNull();
  expect(trialLabel(week, "ios", true)).toBe("1-week");
});

test("Android trusts the store's offer and formats multi-unit periods", () => {
  expect(trialLabel({ price: 0, cycles: 1, periodUnit: "DAY", periodNumberOfUnits: 14 }, "android", false)).toBe("14-day");
  expect(trialLabel({ price: 0, cycles: 2, periodUnit: "MONTH", periodNumberOfUnits: 1 }, "android", false)).toBe("2-month");
});
