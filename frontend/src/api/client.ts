import type { ApiErrorBody } from "./types";

const API_BASE = "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: ApiErrorBody["error"]["field_errors"];
  readonly traceId?: string;
  readonly submission?: ApiErrorBody["submission"];

  constructor(status: number, body?: ApiErrorBody) {
    super(body?.error.message ?? `Сервер вернул ошибку ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body?.error.code ?? "HTTP_ERROR";
    this.fieldErrors = body?.error.field_errors;
    this.traceId = body?.error.trace_id;
    this.submission = body?.submission;
  }
}

let csrfToken = "";

export function setCsrfToken(token: string | null | undefined) {
  csrfToken = token ?? "";
}

function isUnsafe(method: string) {
  return !["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase());
}

async function parseError(response: Response): Promise<ApiErrorBody | undefined> {
  try {
    return (await response.json()) as ApiErrorBody;
  } catch {
    return undefined;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (isUnsafe(method) && csrfToken) headers.set("X-CSRF-Token", csrfToken);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      method,
      headers,
      credentials: "include",
    });
  } catch {
    throw new ApiError(0, {
      error: {
        code: "NETWORK_ERROR",
        message: "Нет связи с сервером. Проверьте подключение и повторите действие.",
      },
    });
  }

  if (!response.ok) throw new ApiError(response.status, await parseError(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get<T>(path: string) {
    return request<T>(path);
  },
  post<T>(path: string, body?: unknown) {
    return request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
  },
  delete<T>(path: string) {
    return request<T>(path, { method: "DELETE" });
  },
  async download(path: string, fallbackName: string) {
    const response = await fetch(`${API_BASE}${path}`, {
      credentials: "include",
      headers: csrfToken ? { "X-CSRF-Token": csrfToken } : undefined,
    });
    if (!response.ok) throw new ApiError(response.status, await parseError(response));
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") ?? "";
    const filename = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i)?.[1];
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename ? decodeURIComponent(filename) : fallbackName;
    anchor.click();
    URL.revokeObjectURL(url);
  },
};

export function query(params: Record<string, string | number | boolean | null | undefined>) {
  const values = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") values.set(key, String(value));
  }
  const serialized = values.toString();
  return serialized ? `?${serialized}` : "";
}

