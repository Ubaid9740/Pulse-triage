// Fetch helpers. Every call goes to the same server that serves this page (or the Vite proxy in dev).

async function call(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const detail = data && (data.detail || data.error);
    const text = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return data;
}

export const get = (path) => call("GET", path);
export const post = (path, body = {}) => call("POST", path, { by: "dispatcher", ...body });
export const enc = encodeURIComponent;
