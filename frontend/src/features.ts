import { useQuery } from "@tanstack/react-query";

import { api } from "@/src/api";

type Features = { experience_profiles?: boolean; experience_builder?: boolean };

/** Feature flags from app_config (admin-editable). Defaults to ON until config loads, matching the backend defaults. */
export function useFeatures() {
  const config = useQuery({ queryKey: ["config"], queryFn: () => api("/config/public") });
  const f: Features = config.data?.features ?? {};
  return {
    profiles: f.experience_profiles !== false,
    builder: f.experience_builder !== false,
  };
}
