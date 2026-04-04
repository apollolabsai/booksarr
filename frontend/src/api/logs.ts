import { useQuery } from "@tanstack/react-query";
import { fetchApi } from "./client";
import type { LogsResponse } from "../types";

export function useLogs(categories: string[] = [], levels: string[] = []) {
  const params = new URLSearchParams();
  for (const category of categories) params.append("category", category);
  for (const level of levels) params.append("level", level);
  const qs = params.toString();
  return useQuery({
    queryKey: ["logs", categories, levels],
    queryFn: () => fetchApi<LogsResponse>(`/logs${qs ? `?${qs}` : ""}`),
    refetchInterval: 5000,
  });
}
