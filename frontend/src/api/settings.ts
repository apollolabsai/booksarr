import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchApi } from "./client";
import type { Settings, ScanStatus, BuildInfo, ApiUsageDay, VisibilityCategories } from "../types";

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => fetchApi<Settings>("/settings"),
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      hardcover_api_key?: string;
      google_books_api_key?: string;
      scan_interval_hours?: number;
      visibility_categories?: VisibilityCategories;
    }) =>
      fetchApi("/settings", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useScanStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["scanStatus"],
    queryFn: () => fetchApi<ScanStatus>("/library/status"),
    refetchInterval: enabled ? 1000 : false,
    refetchIntervalInBackground: true,
  });
}

export function useTriggerScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (force?: boolean) =>
      fetchApi(`/library/scan${force ? "?force=true" : ""}`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scanStatus"] });
    },
  });
}

export function useResetData() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => fetchApi("/settings/reset", { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries();
    },
  });
}

export function useBuildInfo() {
  return useQuery({
    queryKey: ["buildInfo"],
    queryFn: () => fetchApi<BuildInfo>("/settings/build-info"),
    staleTime: Infinity,
  });
}

export function useApiUsage(days: number, enabled: boolean) {
  return useQuery({
    queryKey: ["apiUsage", days],
    queryFn: () => fetchApi<ApiUsageDay[]>(`/settings/api-usage?days=${days}`),
    refetchInterval: enabled ? 5000 : false,
    refetchIntervalInBackground: true,
  });
}
