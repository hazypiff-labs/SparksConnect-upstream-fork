import React, { createContext, useContext, useState } from "react";

import type { Spark } from "@/src/api";

export type Location = { label: string; lat?: number; lng?: number } | null;

export type Draft = {
  relationship: string | null;
  /** Experience Profile (Increment 2). null/"couple" = original Date Spark flow. */
  experienceType: string | null;
  vibes: string[];
  budget: string | null;
  distance: string | null;
  location: Location;
  occasion: string | null;
  surprise: boolean;
  /** Experience Builder (Increment 3) — all optional; null/empty means "not supplied" */
  surpriseMe: boolean;
  partySize: number | null;
  budgetAmount: number | null;
  durationHours: number | null;
  interests: string[];
  transport: string | null;
  dateLabel: string | null;
  timeLabel: string | null;
  customDate: string;
  results: Spark[];
  seenTitles: string[];
  usage: { used: number; limit: number } | null;
};

const initial: Draft = { relationship: null, experienceType: null, vibes: [], budget: null, distance: null, location: null, occasion: null, surprise: false, surpriseMe: false, partySize: null, budgetAmount: null, durationHours: null, interests: [], transport: null, dateLabel: null, timeLabel: null, customDate: "", results: [], seenTitles: [], usage: null };

type WizardCtx = { draft: Draft; update: (patch: Partial<Draft>) => void; reset: () => void };
const Ctx = createContext<WizardCtx | null>(null);

export function WizardProvider({ children }: { children: React.ReactNode }) {
  const [draft, setDraft] = useState<Draft>(initial);
  const update = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const reset = () => setDraft(initial);
  return <Ctx.Provider value={{ draft, update, reset }}>{children}</Ctx.Provider>;
}

export function useWizard() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useWizard must be used inside WizardProvider");
  return ctx;
}
