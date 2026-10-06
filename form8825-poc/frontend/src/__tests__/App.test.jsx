import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { formatAmount, parseAmount } from "../api";
import { listItem, makeDoc } from "./fixtures";

function mockApi(routes) {
  const calls = [];
  global.fetch = vi.fn(async (url, opts = {}) => {
    const method = opts.method ?? "GET";
    calls.push({ url, method, body: opts.body });
    const key = Object.keys(routes).find((k) => {
      const [m, path] = k.split(" ");
      return m === method && url.includes(path);
    });
    const r = key ? routes[key](opts) : { status: 404, body: { detail: "not found" } };
    const status = r.status ?? 200;
    return { ok: status < 400, status, json: async () => r.body };
  });
  return calls;
}

describe("amount helpers", () => {
  it("formats negatives in parentheses like the form", () => {
    expect(formatAmount(-14840)).toBe("(14,840)");
    expect(formatAmount(1734896)).toBe("1,734,896");
  });
  it("parses what reviewers type", () => {
    expect(parseAmount("(3,400)")).toEqual({ ok: true, value: -3400 });
    expect(parseAmount("$12,500")).toEqual({ ok: true, value: 12500 });
    expect(parseAmount("")).toEqual({ ok: true, value: null });
    expect(parseAmount("12a").ok).toBe(false);
  });
});

describe("App", () => {
  let doc;
  beforeEach(() => {
    doc = makeDoc();
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows an empty state when nothing is uploaded", async () => {
    mockApi({ "GET /api/documents": () => ({ body: [] }) });
    render(<App />);
    expect(await screen.findByText("Drop a Form 8825 PDF here")).toBeInTheDocument();
  });

  it("renders extracted values in the form grid with tick marks", async () => {
    mockApi({
      "GET /api/documents/1/history": () => ({ body: [] }),
      "GET /api/documents/1": () => ({ body: doc }),
      "GET /api/documents": () => ({ body: [listItem] }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByTestId("doc-1"));
    expect(await screen.findByTestId("cell-A-2a")).toHaveTextContent("1,000");
    expect(screen.getByTestId("cell-A-19")).toHaveTextContent("700");
    expect(screen.getByTestId("cell-A-18-check")).toHaveTextContent("✓");
    expect(screen.getByTestId("verdict")).toHaveTextContent("Every total adds up.");
    expect(screen.getByTestId("grand-total")).toHaveTextContent("700");
  });

  it("sends an edit with the version it saw and shows the new result", async () => {
    let current = doc;
    const calls = mockApi({
      "GET /api/documents/1/history": () => ({ body: [] }),
      "GET /api/documents/1": () => ({ body: current }),
      "GET /api/documents": () => ({ body: [listItem] }),
      "PATCH /api/line-items/1": () => {
        current = makeDoc({ gross: 1100, manual: true });
        return { body: {} };
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByTestId("doc-1"));
    await user.click(await screen.findByTestId("cell-A-2a"));
    const input = screen.getByTestId("cell-A-2a-input");
    await user.clear(input);
    await user.type(input, "1,100{Enter}");

    await waitFor(() => expect(screen.getByTestId("cell-A-2a")).toHaveTextContent("1,100"));
    const patch = calls.find((c) => c.method === "PATCH");
    expect(JSON.parse(patch.body)).toMatchObject({ value: 1100, expected_version: 1 });
    expect(screen.getByTestId("cell-A-2a-revert")).toBeInTheDocument();
    expect(screen.getByTestId("verdict")).toHaveTextContent("don't add up");
    expect(screen.getByTestId("cell-A-2c-check")).toHaveTextContent("✗");
  });

  it("rejects text that is not an amount without calling the API", async () => {
    const calls = mockApi({
      "GET /api/documents/1/history": () => ({ body: [] }),
      "GET /api/documents/1": () => ({ body: doc }),
      "GET /api/documents": () => ({ body: [listItem] }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByTestId("doc-1"));
    await user.click(await screen.findByTestId("cell-A-3"));
    const input = screen.getByTestId("cell-A-3-input");
    await user.clear(input);
    await user.type(input, "abc{Enter}");
    expect(screen.getByTestId("cell-A-3-error")).toHaveTextContent("Enter whole dollars");
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("explains a failed upload", async () => {
    mockApi({
      "GET /api/documents": () => ({ body: [] }),
      "POST /api/documents": () => ({ status: 422, body: { detail: { code: "not_form_8825", message: "no Form 8825 page found in the document" } } }),
    });
    const user = userEvent.setup();
    render(<App />);
    const file = new File(["%PDF-1.4"], "invoice.pdf", { type: "application/pdf" });
    await user.upload(await screen.findByTestId("file-input"), file);
    const notice = await screen.findByTestId("notice");
    expect(within(notice).getByText(/invoice.pdf could not be extracted: no Form 8825 page found/)).toBeInTheDocument();
  });
});
