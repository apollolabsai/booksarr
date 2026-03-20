import { useQuery } from "@tanstack/react-query";
import { fetchApi } from "./client";
import type { LogsResponse } from "../types";

export function useLogs(category?: string, level?: string) {
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (level) params.set("level", level);
  const qs = params.toString();
  return useQuery({
    queryKey: ["logs", category, level],
    queryFn: () => fetchApi<LogsResponse>(`/logs${qs ? `?${qs}` : ""}`),
    refetchInterval: 5000,
  });
}
