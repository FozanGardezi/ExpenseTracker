/**
 * Talking to the Expense Tracker API (the Python server in api/). Every request carries
 * the session token and the phone's time zone, which decides where days and months start.
 *
 * EXPO_PUBLIC_API_URL says where the server is (see .env.example).
 */
import { getCalendars } from 'expo-localization';

export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '');

let token: string | null = null;
let signedOutHandler: (() => void) | null = null;

export function setToken(value: string | null) {
  token = value;
}

/** Called when the server says the session is over (expired, or signed out elsewhere). */
export function onSignedOut(handler: (() => void) | null) {
  signedOutHandler = handler;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

export function timeZone(): string {
  try {
    return getCalendars()[0]?.timeZone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC';
  } catch {
    return 'UTC';
  }
}

export type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function url(path: string, query?: Query): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === '') continue;
    for (const one of Array.isArray(value) ? value : [value]) {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(one))}`);
    }
  }
  return `${API_URL}${path}${parts.length ? `?${parts.join('&')}` : ''}`;
}

type Options = { query?: Query; body?: unknown; form?: FormData };

async function send(method: string, path: string, { query, body, form }: Options = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json', 'X-Timezone': timeZone() };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch(url(path, query), {
      method,
      headers,
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError(0, `Couldn't reach the server at ${API_URL}. Check your connection.`);
  }
  if (response.status === 401 && token) {
    signedOutHandler?.();
  }
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = undefined;
    }
    const message =
      typeof detail === 'string'
        ? detail
        : detail && typeof detail === 'object' && 'message' in detail
          ? String((detail as { message: unknown }).message)
          : `Something went wrong (${response.status}).`;
    throw new ApiError(response.status, message, detail);
  }
  return response;
}

async function json<T>(method: string, path: string, options?: Options): Promise<T> {
  return (await send(method, path, options)).json() as Promise<T>;
}

export const api = {
  get: <T>(path: string, query?: Query) => json<T>('GET', path, { query }),
  post: <T>(path: string, body?: unknown) => json<T>('POST', path, { body: body ?? {} }),
  put: <T>(path: string, body?: unknown) => json<T>('PUT', path, { body: body ?? {} }),
  patch: <T>(path: string, body?: unknown) => json<T>('PATCH', path, { body: body ?? {} }),
  delete: <T>(path: string) => json<T>('DELETE', path),
  upload: <T>(path: string, form: FormData) => json<T>('POST', path, { form }),
  text: async (path: string, query?: Query) => (await send('GET', path, { query })).text(),
};

export type Message = { message: string };

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.';
}
