import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchApi } from "./client";
import type {
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
    mutationFn: (body: { book_id?: number; query_text: string }) =>
      fetchApi<IrcSearchJob>("/irc/search", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["ircSearchJobs"] });
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
      queryClient.invalidateQueries({ queryKey: ["ircSearchJob", job.id] });
      queryClient.invalidateQueries({ queryKey: ["ircSearchResults", job.id] });
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

export function useIrcDownloadJobs() {
  return useQuery({
    queryKey: ["ircDownloadJobs"],
    queryFn: () => fetchApi<IrcDownloadJob[]>("/irc/download-jobs"),
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  });
}

export function useCreateIrcDownloadJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { search_result_id: number }) =>
      fetchApi<IrcDownloadJob>("/irc/download", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["ircDownloadJobs"] });
      queryClient.invalidateQueries({ queryKey: ["ircStatus"] });
      if (job.search_job_id != null) {
        queryClient.invalidateQueries({ queryKey: ["ircSearchResults", job.search_job_id] });
      }
    },
  });
}
