const BASE_URL = "/api";

export async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = "";
    try {
      const payload = await resp.json();
      if (typeof payload?.detail === "string") {
        detail = payload.detail;
      } else if (payload?.detail) {
        detail = JSON.stringify(payload.detail);
      }
    } catch {
      try {
        detail = await resp.text();
      } catch {
        detail = "";
      }
    }

    throw new Error(detail || `API error: ${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}
