import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fetchApi } from "./client";
import type { Author, AuthorDetail } from "../types";

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
