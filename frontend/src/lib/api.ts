import { row, text, type Row } from './data.ts';
export class ApiError extends Error {
  status: number;
  details: Row;
  constructor(message: string, status: number, details: Row = {}) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

let csrf = '';
export function setCsrf(token: string) { csrf = token; }
export type RequestOptions = {
  method?: string;
  body?: Row | FormData;
  signal?: AbortSignal;
  download?: boolean;
};
export async function request(path: string, options: RequestOptions = {}): Promise<Row> {
  if (!path.startsWith('/backend/') && !path.startsWith('/config/'))
    throw new Error('Unsupported API path');
  const method = options.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };
  const multipart = options.body instanceof FormData;
  if (multipart && csrf && !(options.body as FormData).has('csrf_token'))
    (options.body as FormData).set('csrf_token', csrf);
  if (options.body && !multipart)
    headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrf)
    headers['X-CSRF-Token'] = csrf;
  const response = await fetch(path, {
    method, credentials: 'same-origin', cache: 'no-store', headers, signal: options.signal,
    body: options.body ? multipart ? options.body as FormData : JSON.stringify(options.body) : undefined,
  });
  const attachment = response.headers.get('content-disposition');
  if (response.ok && (attachment || options.download)) {
    // Some server-side VPN failures return JSON with HTTP 200. Never save those as a configuration.
    if (!response.headers.get('content-type')?.includes('application/json')) {
      const blob = await response.blob();
      const filename = (attachment?.match(/filename="?([^";]+)/i)?.[1] ?? 'heist.ovpn').split(/[\\/]/).pop()!.replace(/[\u0000-\u001f]/g, '');
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return { success: true, message: 'Download ready.' };
    }
  }
  let data: Row;
  try {
    data = row(await response.json());
  }
  catch {
    throw new ApiError('The server returned an unexpected response. Please retry.', response.status);
  }
  if (!response.ok || data.success === false) {
    const errors = Array.isArray(data.errors) ? data.errors.map(v => text(v)).join(' ') : '';
    if (response.status === 401 && !path.includes('/login.php'))
      window.dispatchEvent(new Event('heist:session-expired'));
    throw new ApiError(text(data.message) || errors || `Request failed (${response.status}).`, response.status, data);
  }
  return data;
}
export const post = (name: string, body: Row | FormData, signal?: AbortSignal) => request(`/backend/${name}.php`, { method: 'POST', body, signal });
