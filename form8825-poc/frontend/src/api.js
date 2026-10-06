const BASE = import.meta.env.VITE_API_BASE ?? "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}/api${path}`, options);
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body.detail;
    const message =
      typeof detail === "string" ? detail : detail?.message ?? `Request failed (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    err.code = detail?.code;
    err.documentId = detail?.document_id;
    throw err;
  }
  return body;
}

export const api = {
  listDocuments: () => request("/documents"),
  getDocument: (id) => request(`/documents/${id}`),
  getHistory: (id) => request(`/documents/${id}/history`),
  deleteDocument: (id) => request(`/documents/${id}`, { method: "DELETE" }),
  upload: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/documents", { method: "POST", body: form });
  },
  updateLine: (id, value, expectedVersion, reason) =>
    request(`/line-items/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value, expected_version: expectedVersion, reason, changed_by: "ui-user" }),
    }),
  revertLine: (id) => request(`/line-items/${id}/revert`, { method: "POST" }),
  updateAddress: (id, address) =>
    request(`/properties/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ address, changed_by: "ui-user" }),
    }),
  exportUrl: (id, source = "current") => `${BASE}/api/documents/${id}/export?source=${source}`,
  fileUrl: (id) => `${BASE}/api/documents/${id}/file`,
};

export function formatAmount(value) {
  if (value === null || value === undefined) return "";
  const abs = Math.abs(value).toLocaleString("en-US");
  return value < 0 ? `(${abs})` : abs;
}

/** Accepts "1,234", "(1,234)", "-1234", "$1,234" and "" (clears the line). */
export function parseAmount(text) {
  const s = String(text).trim();
  if (s === "") return { ok: true, value: null };
  const negative = /^\(.*\)$/.test(s) || s.startsWith("-");
  const digits = s.replace(/[()$,\s-]/g, "");
  if (!/^\d+$/.test(digits)) return { ok: false, error: "Enter whole dollars, e.g. 12,500 or (3,400)" };
  const n = parseInt(digits, 10);
  return { ok: true, value: negative ? -n : n };
}

export function formatDate(iso) {
  if (!iso) return "";
  const withZone = /[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`; // SQLite drops the zone
  return new Date(withZone).toLocaleString();
}
