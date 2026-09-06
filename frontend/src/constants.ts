export const RELATIONSHIPS = [
  { key: "partner", label: "Partner", emoji: "❤️" },
  { key: "date", label: "Date", emoji: "💘" },
  { key: "friends", label: "Friends", emoji: "👫" },
  { key: "family", label: "Family", emoji: "👨‍👩‍👧" },
  { key: "group", label: "Group", emoji: "🎉" },
  { key: "special", label: "Someone Special", emoji: "✨" },
];

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
