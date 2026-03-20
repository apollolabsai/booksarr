import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchApi } from "./client";
import type { Settings, ScanStatus, BuildInfo } from "../types";

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => fetchApi<Settings>("/settings"),
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { hardcover_api_key?: string }) =>
      fetchApi("/settings", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useScanStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["scanStatus"],
    queryFn: () => fetchApi<ScanStatus>("/library/status"),
    refetchInterval: enabled ? 2000 : false,
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

export function useBuildInfo() {
  return useQuery({
    queryKey: ["buildInfo"],
    queryFn: () => fetchApi<BuildInfo>("/settings/build-info"),
    staleTime: Infinity,
  });
}
