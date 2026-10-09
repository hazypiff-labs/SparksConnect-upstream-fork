import { useQuery } from "@tanstack/react-query";

import { api } from "@/src/api";

type Features = { experience_profiles?: boolean; experience_builder?: boolean };

/**
 * Feature flags from app_config (admin-editable).
 * `ready` is false until the config request has settled — screens must not decide which
 * experience UI to render before then (prevents a flash of Experience Builder UI when the flag is OFF).
 * If the request fails (offline), flags fall back to the backend defaults (ON).
 */
export function useFeatures() {
  const config = useQuery({ queryKey: ["config"], queryFn: () => api("/config/public"), retry: 1, staleTime: 60_000 });
  const f: Features = config.data?.features ?? {};
  const ready = config.isSuccess || config.isError;
  return {
    ready,
    profiles: ready && f.experience_profiles !== false,
    builder: ready && f.experience_builder !== false,
  };
}
