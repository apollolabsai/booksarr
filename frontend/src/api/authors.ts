import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchApi } from "./client";
import type {
  Author,
  AuthorDetail,
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
