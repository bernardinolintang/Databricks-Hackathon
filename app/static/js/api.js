// JSON API client with in-memory caching of identical GET requests.

const cache = new Map();

export class ApiError extends Error {}

export async function api(path, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    query.set(key, value);
  }
  const url = `/api/${path}${query.toString() ? `?${query}` : ""}`;
  if (cache.has(url)) return cache.get(url);

  const request = fetch(url, { headers: { Accept: "application/json" } }).then(async (response) => {
    let body;
    try {
      body = await response.json();
    } catch {
      throw new ApiError(`The server returned an unreadable response (${response.status}).`);
    }
    if (!response.ok) {
      const detail = body?.error || (Array.isArray(body?.detail) ? body.detail.map((d) => d.msg).join("; ") : body?.detail);
      throw new ApiError(detail || `Request failed (${response.status}).`);
    }
    return body;
  });
  cache.set(url, request);
  request.catch(() => cache.delete(url));
  return request;
}
