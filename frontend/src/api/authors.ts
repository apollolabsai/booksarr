import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchApi } from "./client";
import type {
  Author,
  AuthorDetail,
  AuthorDirectoryMergeResponse,
  AuthorPortraitSearchResponse,
  AuthorPortraitOptionsResponse,
  AuthorSearchResponse,
} from "../types";

export function useAuthors(sort: string = "name", search: string = "") {
  return useQuery({
    queryKey: ["authors", sort, search],
    queryFn: () => {
      const params = new URLSearchParams({ sort });
      if (search) params.set("search", search);
      return fetchApi<Author[]>(`/authors?${params}`);
    },
    placeholderData: keepPreviousData,
  });
}

export function useAuthor(id: number) {
  return useQuery({
    queryKey: ["authors", id],
    queryFn: () => fetchApi<AuthorDetail>(`/authors/${id}`),
    enabled: !!id,
  });
}

export function useAuthorPortraitOptions(authorId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["authorPortraitOptions", authorId],
    queryFn: () => fetchApi<AuthorPortraitOptionsResponse>(`/authors/${authorId}/portrait-options`),
    enabled: enabled && !!authorId,
  });
}

export function useAuthorPortraitSearch(authorId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["authorPortraitSearch", authorId],
    queryFn: () => fetchApi<AuthorPortraitSearchResponse>(`/authors/${authorId}/portrait-search`),
    enabled: enabled && !!authorId,
  });
}

export function useSetAuthorPortrait() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      authorId,
      source,
      image_url,
      page_url,
    }: {
      authorId: number;
      source: string;
      image_url: string;
      page_url?: string | null;
    }) =>
      fetchApi(`/authors/${authorId}/portrait-selection`, {
        method: "POST",
        body: JSON.stringify({ source, image_url, page_url }),
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["authors"] });
      queryClient.invalidateQueries({ queryKey: ["authors", variables.authorId] });
      queryClient.invalidateQueries({ queryKey: ["authorPortraitOptions", variables.authorId] });
      queryClient.invalidateQueries({ queryKey: ["authorPortraitSearch", variables.authorId] });
    },
  });
}

export function useSearchHardcoverAuthors() {
  return useMutation({
    mutationFn: (query: string) =>
      fetchApi<AuthorSearchResponse>(`/authors/hardcover-search?query=${encodeURIComponent(query)}`),
  });
}

export function useAddAuthorFromHardcover() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (hardcoverId: number) =>
      fetchApi<Author>("/authors/add-from-hardcover", {
        method: "POST",
        body: JSON.stringify({ hardcover_id: hardcoverId }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["authors"] });
    },
  });
}

export function useRefreshAuthor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (authorId: number) =>
      fetchApi(`/authors/${authorId}/refresh`, {
        method: "POST",
      }),
    onSuccess: (_, authorId) => {
      queryClient.invalidateQueries({ queryKey: ["authors"] });
      queryClient.invalidateQueries({ queryKey: ["authors", authorId] });
      queryClient.invalidateQueries({ queryKey: ["books"] });
      queryClient.invalidateQueries({ queryKey: ["hiddenBooks"] });
    },
  });
}

export function useRemoveAuthor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (authorId: number) =>
      fetchApi(`/authors/${authorId}`, {
        method: "DELETE",
      }),
    onSuccess: (_, authorId) => {
      queryClient.invalidateQueries({ queryKey: ["authors"] });
      queryClient.removeQueries({ queryKey: ["authors", authorId] });
      queryClient.invalidateQueries({ queryKey: ["books"] });
      queryClient.invalidateQueries({ queryKey: ["hiddenBooks"] });
    },
  });
}

export function useMergeAuthorDirectories() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      authorId,
      targetDirectoryId,
    }: {
      authorId: number;
      targetDirectoryId: number;
    }) =>
      fetchApi<AuthorDirectoryMergeResponse>(`/authors/${authorId}/merge-directories`, {
        method: "POST",
        body: JSON.stringify({ target_directory_id: targetDirectoryId }),
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["authors"] });
      queryClient.invalidateQueries({ queryKey: ["authors", variables.authorId] });
      queryClient.invalidateQueries({ queryKey: ["books"] });
      queryClient.invalidateQueries({ queryKey: ["hiddenBooks"] });
    },
  });
}
