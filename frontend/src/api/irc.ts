import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchApi } from "./client";
import type {
  IrcBulkDownloadBatch,
  IrcDownloadFeedEntry,
  IrcBulkSearchResponse,
  IrcDownloadJob,
  IrcSearchJob,
  IrcSearchResult,
  IrcSettings,
  IrcWorkerStatus,
} from "../types";

export function useIrcSettings() {
  return useQuery({
    queryKey: ["ircSettings"],
    queryFn: () => fetchApi<IrcSettings>("/irc/settings"),
  });
}

export function useUpdateIrcSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      enabled?: boolean;
      server?: string;
      port?: number;
      use_tls?: boolean;
      nickname?: string;
      username?: string;
      real_name?: string;
      channel?: string;
      channel_password?: string;
      vpn_enabled?: boolean;
      vpn_region?: string;
      vpn_username?: string;
      vpn_password?: string;
      auto_move_to_library?: boolean;
    }) => fetchApi("/irc/settings", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ircSettings"] });
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
    },
  });
}

export function useIrcStatus(enabled: boolean = true) {
  return useQuery({
    queryKey: ["ircStatus"],
    queryFn: () => fetchApi<IrcWorkerStatus>("/irc/status"),
    refetchInterval: enabled ? 3000 : false,
    refetchIntervalInBackground: true,
  });
}

export function useConnectIrc() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => fetchApi("/irc/connect", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ircStatus"] }),
  });
}

export function useDisconnectIrc() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => fetchApi("/irc/disconnect", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ircStatus"] }),
  });
}

export function useIrcSearchJobs() {
  return useQuery({
    queryKey: ["ircSearchJobs"],
    queryFn: () => fetchApi<IrcSearchJob[]>("/irc/search-jobs"),
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  });
}

export function useCreateIrcSearchJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { book_id?: number; query_text: string; auto_download?: boolean }) =>
      fetchApi<IrcSearchJob>("/irc/search", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["ircSearchJobs"] });
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadsFeed"] });
      queryClient.invalidateQueries({ queryKey: ["ircSearchJob", job.id] });
      queryClient.invalidateQueries({ queryKey: ["ircSearchResults", job.id] });
    },
  });
}

export function useCreateBulkIrcSearchJobs() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      book_ids: number[];
      skip_owned?: boolean;
      auto_download_single_result?: boolean;
    }) => fetchApi<IrcBulkSearchResponse>("/irc/search/bulk", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["ircSearchJobs"] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadJobs"] });
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadsFeed"] });
      for (const item of response.queued) {
        queryClient.setQueryData(["ircSearchJob", item.job.id], item.job);
        queryClient.invalidateQueries({ queryKey: ["ircSearchResults", item.job.id] });
      }
    },
  });
}

export function useCreateIrcBulkBatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { book_ids: number[] }) =>
      fetchApi<IrcBulkDownloadBatch>("/irc/bulk-batches", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (batch) => {
      queryClient.setQueryData(["ircBulkBatch", batch.id], batch);
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
      queryClient.invalidateQueries({ queryKey: ["ircSearchJobs"] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadJobs"] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadsFeed"] });
    },
  });
}

export function useIrcBulkBatch(batchId: number | null, enabled: boolean = true) {
  return useQuery({
    queryKey: ["ircBulkBatch", batchId],
    queryFn: () => fetchApi<IrcBulkDownloadBatch>(`/irc/bulk-batches/${batchId}`),
    enabled: enabled && batchId != null,
    refetchInterval: enabled && batchId != null ? 3000 : false,
    refetchIntervalInBackground: true,
  });
}

export function usePauseIrcBulkBatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (batchId: number) =>
      fetchApi<IrcBulkDownloadBatch>(`/irc/bulk-batches/${batchId}/pause`, { method: "POST" }),
    onSuccess: (batch) => {
      queryClient.setQueryData(["ircBulkBatch", batch.id], batch);
      queryClient.invalidateQueries({ queryKey: ["ircBulkBatch", batch.id] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadsFeed"] });
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
    },
  });
}

export function useResumeIrcBulkBatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (batchId: number) =>
      fetchApi<IrcBulkDownloadBatch>(`/irc/bulk-batches/${batchId}/resume`, { method: "POST" }),
    onSuccess: (batch) => {
      queryClient.setQueryData(["ircBulkBatch", batch.id], batch);
      queryClient.invalidateQueries({ queryKey: ["ircBulkBatch", batch.id] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadsFeed"] });
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
    },
  });
}

export function useCancelIrcBulkBatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (batchId: number) =>
      fetchApi<IrcBulkDownloadBatch>(`/irc/bulk-batches/${batchId}/cancel`, { method: "POST" }),
    onSuccess: (batch) => {
      queryClient.setQueryData(["ircBulkBatch", batch.id], batch);
      queryClient.invalidateQueries({ queryKey: ["ircBulkBatch", batch.id] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadsFeed"] });
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
    },
  });
}

export function useIrcDownloadsFeed(enabled: boolean = true) {
  return useQuery({
    queryKey: ["ircDownloadsFeed"],
    queryFn: () => fetchApi<IrcDownloadFeedEntry[]>("/irc/downloads-feed"),
    enabled,
    refetchInterval: enabled ? 3000 : false,
    refetchIntervalInBackground: true,
  });
}

export function useClearIrcDownloadsFeed() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => fetchApi("/irc/downloads-feed", { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ircDownloadsFeed"] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadJobs"] });
      queryClient.invalidateQueries({ queryKey: ["ircSearchJobs"] });
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
    },
  });
}

export function useIrcSearchJob(jobId: number | null, enabled: boolean = true) {
  return useQuery({
    queryKey: ["ircSearchJob", jobId],
    queryFn: () => fetchApi<IrcSearchJob>(`/irc/search-jobs/${jobId}`),
    enabled: enabled && jobId != null,
    refetchInterval: enabled && jobId != null ? 3000 : false,
    refetchIntervalInBackground: true,
  });
}

export function useIrcSearchResults(jobId: number | null, enabled: boolean = true) {
  return useQuery({
    queryKey: ["ircSearchResults", jobId],
    queryFn: () => fetchApi<IrcSearchResult[]>(`/irc/search-jobs/${jobId}/results`),
    enabled: enabled && jobId != null,
    refetchInterval: enabled && jobId != null ? 3000 : false,
    refetchIntervalInBackground: true,
  });
}

export function useIrcDownloadJobs(enabled: boolean = true) {
  return useQuery({
    queryKey: ["ircDownloadJobs"],
    queryFn: () => fetchApi<IrcDownloadJob[]>("/irc/download-jobs"),
    enabled,
    refetchInterval: enabled ? 3000 : false,
    refetchIntervalInBackground: true,
  });
}

export function useIrcDownloadJob(jobId: number | null, enabled: boolean = true) {
  return useQuery({
    queryKey: ["ircDownloadJob", jobId],
    queryFn: () => fetchApi<IrcDownloadJob>(`/irc/download-jobs/${jobId}`),
    enabled: enabled && jobId != null,
    refetchInterval: enabled && jobId != null ? 3000 : false,
    refetchIntervalInBackground: true,
  });
}

export function useCreateIrcDownloadJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { search_result_id: number }) =>
      fetchApi<IrcDownloadJob>("/irc/download", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (job) => {
      queryClient.setQueryData(["ircDownloadJob", job.id], job);
      queryClient.invalidateQueries({ queryKey: ["ircDownloadJobs"] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadJob", job.id] });
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
      queryClient.invalidateQueries({ queryKey: ["ircDownloadsFeed"] });
      if (job.search_job_id != null) {
        queryClient.invalidateQueries({ queryKey: ["ircSearchResults", job.search_job_id] });
      }
    },
  });
}
