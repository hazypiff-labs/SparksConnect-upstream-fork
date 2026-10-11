export const RELATIONSHIPS = [
  { key: "partner", label: "Partner", emoji: "❤️" },
  { key: "date", label: "Date", emoji: "💘" },
  { key: "friends", label: "Friends", emoji: "👫" },
  { key: "family", label: "Family", emoji: "👨‍👩‍👧" },
  { key: "group", label: "Group", emoji: "🎉" },
  { key: "special", label: "Someone Special", emoji: "✨" },
];

/** Experience Profiles (Increment 2). "couple" is the original Date Spark flow, untouched. */
export type ExperienceProfile = {
  key: string;
  label: string;
  emoji: string;
  headline: string;
  subtitle: string;
  /** which existing "who" cards to show; null = no cards (relationship is fixed) */
  relationships: string[] | null;
  defaultRelationship: string | null;
  locationTitle: string;
};

export const EXPERIENCE_PROFILES: ExperienceProfile[] = [
  { key: "couple", label: "Couple", emoji: "❤️", headline: "Who are you spending time with?", subtitle: "Pick one. We'll tailor every Spark to this connection.", relationships: RELATIONSHIPS.map((r) => r.key), defaultRelationship: null, locationTitle: "Starting from" },
  { key: "friends", label: "Friends", emoji: "👫", headline: "Who's coming along?", subtitle: "Outings built for conversation, laughs and shared moments.", relationships: ["friends", "group"], defaultRelationship: "friends", locationTitle: "Starting from" },
  { key: "family", label: "Family", emoji: "👨‍👩‍👧", headline: "Who's in the family plan?", subtitle: "Inclusive, all-ages experiences everyone can enjoy.", relationships: ["family", "group"], defaultRelationship: "family", locationTitle: "Starting from" },
  { key: "celebration", label: "Celebration", emoji: "🥂", headline: "Who are you celebrating with?", subtitle: "Pick the people, then choose the occasion below.", relationships: RELATIONSHIPS.map((r) => r.key), defaultRelationship: null, locationTitle: "Starting from" },
  { key: "travel", label: "Travel", emoji: "🧳", headline: "Who's traveling with you?", subtitle: "Local gems and easy logistics for a place you're visiting.", relationships: ["solo", "partner", "friends", "family", "group"], defaultRelationship: null, locationTitle: "Where are you visiting?" },
  { key: "solo", label: "Solo", emoji: "🧘", headline: "A moment just for you", subtitle: "Experiences that feel great to do on your own.", relationships: null, defaultRelationship: "solo", locationTitle: "Starting from" },
];

export const SOLO_RELATIONSHIP = { key: "solo", label: "Just me", emoji: "🧘" };

export function relationshipOption(key: string) {
  return key === SOLO_RELATIONSHIP.key ? SOLO_RELATIONSHIP : RELATIONSHIPS.find((r) => r.key === key);
}

export function profileFor(key: string | null | undefined): ExperienceProfile {
  return EXPERIENCE_PROFILES.find((p) => p.key === key) ?? EXPERIENCE_PROFILES[0];
}

/** Experience Builder (Increment 3) */
export const PARTY_DEFAULTS: Record<string, number> = { couple: 2, friends: 4, family: 4, celebration: 6, travel: 2, solo: 1 };
export const QUICK_AMOUNTS = [50, 100, 150, 250];
export const DURATIONS = [
  { key: 1, label: "1 hour" },
  { key: 2, label: "2 hours" },
  { key: 3, label: "3 hours" },
  { key: 4, label: "Evening" },
  { key: 5, label: "Half day" },
  { key: 8, label: "Full day" },
];
export const TRANSPORTS = [
  { key: "drive", label: "Drive", emoji: "🚗" },
  { key: "walk", label: "Walk", emoji: "🚶" },
  { key: "transit", label: "Transit", emoji: "🚇" },
];
const BASE_INTERESTS = ["Live music", "Coffee", "Cocktails", "Outdoors", "Art", "Games", "Sports", "Food trucks", "Wine", "Dancing", "Markets", "Bookstores"];
const PROFILE_INTERESTS: Record<string, string[]> = {
  couple: ["Sunset spots", "Dessert"],
  friends: ["Trivia", "Karaoke"],
  family: ["Kid-friendly", "Playgrounds", "Animals"],
  celebration: ["Private rooms", "Cake"],
  travel: ["Landmarks", "Local eats", "Views"],
  solo: ["Classes", "Quiet cafés", "Journaling"],
};
export function interestsFor(profile: string) {
  return [...(PROFILE_INTERESTS[profile] ?? []), ...BASE_INTERESTS];
}
/** Map a free-form amount onto the existing budget tier so the legacy `budget` field is always valid. */
export function tierForAmount(amount: number): string {
  if (amount <= 0) return "free";
  if (amount <= 25) return "under25";
  if (amount <= 50) return "25-50";
  if (amount <= 100) return "50-100";
  return "100plus";
}

export const VIBES = [
  { key: "romantic", label: "Romantic", emoji: "❤️" },
  { key: "fun", label: "Fun & Playful", emoji: "😂" },
  { key: "adventurous", label: "Adventurous", emoji: "🔥" },
  { key: "relaxing", label: "Relaxing", emoji: "🌿" },
  { key: "foodie", label: "Foodie", emoji: "🍽️" },
  { key: "creative", label: "Creative", emoji: "🎨" },
  { key: "entertainment", label: "Entertainment", emoji: "🎬" },
  { key: "different", label: "Something Different", emoji: "🌙" },
];

export const BUDGETS = [
  { key: "free", label: "FREE" },
  { key: "under25", label: "$25 OR LESS" },
  { key: "25-50", label: "$25–$50" },
  { key: "50-100", label: "$50–$100" },
  { key: "100plus", label: "$100+" },
];

export const DISTANCES = [
  { key: "5", label: "5 miles" },
  { key: "10", label: "10 miles" },
  { key: "25", label: "25 miles" },
  { key: "anywhere", label: "Anywhere" },
];

export const DATE_OPTIONS = ["Today", "Tomorrow", "This Weekend", "Choose a Date"];
export const TIME_OPTIONS = ["10:00 AM", "12:00 PM", "2:00 PM", "5:00 PM", "6:00 PM", "7:00 PM", "8:00 PM"];

export const IMAGES = {
  welcome:
    "https://images.unsplash.com/photo-1571771826307-98d0d0999028?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NTY2NjZ8MHwxfHNlYXJjaHwxfHxjb3VwbGUlMjBsYXVnaGluZyUyMHN1bnNldHxlbnwwfHx8fDE3ODg2MjEwOTl8MA&ixlib=rb-4.1.0&q=85",
  cards: [
    "https://images.pexels.com/photos/5047002/pexels-photo-5047002.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
    "https://images.unsplash.com/photo-1688437307687-fe226bddfab1?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA1ODh8MHwxfHNlYXJjaHwxfHxjb3p5JTIwZGlubmVyJTIwdGFibGV8ZW58MHx8fHwxNzg4NjIxMTEzfDA&ixlib=rb-4.1.0&q=85",
    "https://images.unsplash.com/photo-1597120590849-a1d5a743d155?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjY2NzN8MHwxfHNlYXJjaHwxfHxzY2VuaWMlMjBuYXR1cmUlMjB3YWxrfGVufDB8fHx8MTc4ODYyMTA5OXww&ixlib=rb-4.1.0&q=85",
  ],
  share:
    "https://images.unsplash.com/photo-1508564733209-edec8a954e40?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDk1ODB8MHwxfHNlYXJjaHwxfHxzcGFya2xlciUyMG5pZ2h0fGVufDB8fHx8MTc4ODYyMTA5OXww&ixlib=rb-4.1.0&q=85",
  empty:
    "https://images.unsplash.com/photo-1595981235830-8f54193a692f?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAzNzl8MHwxfHNlYXJjaHwxfHxibGFuayUyMHBvbGFyb2lkfGVufDB8fHx8MTc4ODYyMTExM3ww&ixlib=rb-4.1.0&q=85",
};

export const OCCASIONS = [
  { key: "anniversary", label: "Anniversary", emoji: "💍" },
  { key: "birthday", label: "Birthday", emoji: "🎂" },
  { key: "celebration", label: "Celebration", emoji: "🥂" },
  { key: "first-date", label: "First Date", emoji: "🌹" },
  { key: "make-up", label: "Make-up Date", emoji: "🕊️" },
  { key: "just-because", label: "Just Because", emoji: "🎈" },
];

export const PREMIUM_FEATURES = [
  "Unlimited Sparks every month",
  "Advanced personalization",
  "Multi-stop, detailed itineraries",
  "Surprise Spark mode",
  "Special occasion planning",
  "Unlimited saved Sparks",
];

export function cardImage(index: number) {
  return IMAGES.cards[index % IMAGES.cards.length];
}

export function labelFor(list: { key: string; label: string }[], key: string | null | undefined) {
  return list.find((x) => x.key === key)?.label ?? key ?? "";
}

/** Legal links shown on the paywall, sign-up and profile (App Store 3.1.2 / 5.1.1). Set per build. */
export const LEGAL = {
  privacy: process.env.EXPO_PUBLIC_PRIVACY_URL ?? "",
  // Apple's standard EULA unless the app publishes its own terms.
  terms: process.env.EXPO_PUBLIC_TERMS_URL || "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/",
};

/** Public origin for invitation links, e.g. https://datespark.app (served by the backend: /s/<id> + app-link files). */
export const SHARE_BASE_URL = (process.env.EXPO_PUBLIC_SHARE_BASE_URL ?? "").replace(/\/+$/, "");
