import { ApiRequestError, parseErrorBody } from "./api-types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Re-exported so existing `import { ApiRequestError } from "@/lib/api-types"`
// call sites keep resolving to the one class in api-types.
export { ApiRequestError };

export interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
}

function isFormData(body: unknown): body is FormData {
  return body instanceof FormData;
}

/** The one low-level request function: JSON-encodes the body (FormData passes
 * through) and returns the raw Response. Exported for streaming callers (SSE)
 * that can't use apiFetch, which always JSON-parses the full body. The API
 * runs in local mode, so there is no auth header or refresh handling. */
export function apiRequest(path: string, options: ApiFetchOptions = {}): Promise<Response> {
  const { body, headers, ...rest } = options;
  const merged = new Headers(headers);
  // FormData sets its own multipart boundary Content-Type — never override it.
  if (body !== undefined && !isFormData(body)) merged.set("Content-Type", "application/json");

  return fetch(`${API_URL}${path}`, {
    ...rest,
    headers: merged,
    body: body === undefined ? undefined : isFormData(body) ? body : JSON.stringify(body),
  });
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const response = await apiRequest(path, options);

  if (!response.ok) {
    throw new ApiRequestError(response.status, await parseErrorBody(response));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** For binary responses (e.g. figure images) that shouldn't be JSON-parsed. */
export async function apiFetchBlob(path: string, options: ApiFetchOptions = {}): Promise<Blob> {
  const response = await apiRequest(path, options);

  if (!response.ok) {
    throw new ApiRequestError(response.status, await parseErrorBody(response));
  }

  return response.blob();
}
