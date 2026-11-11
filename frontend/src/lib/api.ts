// Thin typed client for the FastAPI backend. Requests go to /api/* (proxied by Next.js rewrites),
// so no backend URL or secret is ever embedded in client code.

export class ApiError extends Error {
  status: number;
  details: string[];
  code?: string;
  constructor(message: string, status: number, details: string[] = [], code?: string) {
    super(message);
    this.status = status;
    this.details = details;
    this.code = code;
  }
}

interface ErrorBody {
  detail?: string | { message?: string; details?: string[]; code?: string } | { msg: string }[];
  errors?: { field: string; message: string }[];
}

export function errorFromBody(status: number, body: unknown): ApiError {
  const b = (body ?? {}) as ErrorBody;
  if (typeof b.detail === "string") {
    const details = (b.errors ?? []).map((e) => (e.field ? `${e.field}: ${e.message}` : e.message));
    return new ApiError(b.detail, status, details);
  }
  if (b.detail && !Array.isArray(b.detail) && typeof b.detail === "object") {
    return new ApiError(b.detail.message ?? "Ошибка запроса.", status, b.detail.details ?? [], b.detail.code);
  }
  if (status === 0) return new ApiError("Нет соединения с сервером.", 0);
  if (status >= 500) return new ApiError("Сервер временно недоступен. Повторите попытку.", status);
  return new ApiError("Ошибка запроса.", status);
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal,
  extraHeaders?: Record<string, string>): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      signal,
      headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...(extraHeaders ?? {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("Нет соединения с сервером. Проверьте, что бэкенд запущен.", 0);
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) throw errorFromBody(res.status, data);
  return data as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>("GET", path, undefined, signal),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
    request<T>("POST", path, body ?? {}, undefined, headers),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

/** Upload with progress (XHR gives upload progress; fetch does not). */
export function uploadFile<T>(path: string, file: File, onProgress: (pct: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onerror = () => reject(new ApiError("Нет соединения с сервером.", 0));
    xhr.ontimeout = () => reject(new ApiError("Превышено время ожидания.", 0));
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        data = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else reject(errorFromBody(xhr.status, data));
    };
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
