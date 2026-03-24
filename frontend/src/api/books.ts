import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchApi } from "./client";
import type { Book, HiddenBook, BookCoverOptionsResponse } from "../types";

export function useBooks(sort: string = "title", owned?: boolean, search: string = "") {
  return useQuery({
    queryKey: ["books", sort, owned, search],
    queryFn: () => {
      const params = new URLSearchParams({ sort });
      if (owned !== undefined) params.set("owned", String(owned));
      if (search) params.set("search", search);
      return fetchApi<Book[]>(`/books?${params}`);
    },
    placeholderData: keepPreviousData,
  });
}

export function useHiddenBooks(search: string = "") {
  return useQuery({
    queryKey: ["hiddenBooks", search],
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      return fetchApi<HiddenBook[]>(`/books/hidden${params.toString() ? `?${params}` : ""}`);
    },
    placeholderData: keepPreviousData,
  });
}

export function useRefreshBook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (bookId: number) =>
      fetchApi(`/books/${bookId}/refresh`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
      queryClient.invalidateQueries({ queryKey: ["hiddenBooks"] });
      queryClient.invalidateQueries({ queryKey: ["authors"] });
    },
  });
}

export function useBookCoverOptions(bookId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["bookCoverOptions", bookId],
    queryFn: () => fetchApi<BookCoverOptionsResponse>(`/books/${bookId}/cover-options`),
    enabled: enabled && !!bookId,
  });
}

export function useSetBookCover() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ bookId, source }: { bookId: number; source: string }) =>
      fetchApi(`/books/${bookId}/cover-selection`, {
        method: "POST",
        body: JSON.stringify({ source }),
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
      queryClient.invalidateQueries({ queryKey: ["hiddenBooks"] });
      queryClient.invalidateQueries({ queryKey: ["authors"] });
      queryClient.invalidateQueries({ queryKey: ["bookCoverOptions", variables.bookId] });
    },
  });
}

export function useSetBookVisibility() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ bookId, action }: { bookId: number; action: "hide" | "show" | "reset" }) =>
      fetchApi(`/books/${bookId}/visibility`, {
        method: "POST",
        body: JSON.stringify({ action }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
      queryClient.invalidateQueries({ queryKey: ["hiddenBooks"] });
      queryClient.invalidateQueries({ queryKey: ["authors"] });
    },
  });
}
