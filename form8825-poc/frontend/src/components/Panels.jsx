import AmountCell from "./AmountCell";
import { formatAmount, formatDate } from "../api";

const CHECKED = new Set(["20a", "20b", "23"]);

/** Form-level lines 20a-23 plus the grand total net income across properties. */
export function SummaryPanel({ doc, onSave, onRevert }) {
  const checkFor = (code) => doc.validation.checks.find((c) => c.scope === "form" && c.line === code);
  return (
    <table className="summary" data-testid="summary">
      <tbody>
        {doc.summary_lines.map((line) => (
          <tr key={line.line_code} data-testid={`summary-${line.line_code}`}>
            <td className="col-line"><span className="line-box">{line.line_code}</span></td>
            <th scope="row" className="col-desc">{line.label}</th>
            <AmountCell
              line={line}
              testId={`cell-form-${line.line_code}`}
              check={CHECKED.has(line.line_code) ? checkFor(line.line_code) : undefined}
              onSave={onSave}
              onRevert={onRevert}
            />
          </tr>
        ))}
        <tr className="grand-total">
          <td className="col-line" />
          <th scope="row" className="col-desc">Grand total net income (sum of line 19 for all properties)</th>
          <td className="cell" data-testid="grand-total">{formatAmount(doc.grand_total_net_income)}</td>
        </tr>
      </tbody>
    </table>
  );
}

const ACTION_TEXT = {
  extracted: "Extracted from PDF",
  failed: "Extraction failed",
  updated: "Changed",
  reverted: "Reverted",
};

export function HistoryPanel({ entries }) {
  if (!entries.length) return <p className="muted">No changes yet.</p>;
  return (
    <ol className="history" data-testid="history">
      {entries.map((e) => (
        <li key={e.id} className={`history-${e.action}`}>
          <div className="history-what">
            <strong>{ACTION_TEXT[e.action] ?? e.action}</strong>
            {e.entity_type !== "document" && (
              <span>
                {" "}
                {e.property_label ? `property ${e.property_label}, ` : "form, "}
                {e.field === "address" ? "address" : `line ${e.field}`}
              </span>
            )}
          </div>
          {e.entity_type !== "document" && (
            <div className="history-values">
              <span className="old">{fmt(e.old_value, e.field)}</span>
              <span aria-hidden="true"> to </span>
              <span className="new">{fmt(e.new_value, e.field)}</span>
            </div>
          )}
          <div className="history-meta">
            {e.actor}, {formatDate(e.created_at)}
            {e.reason && e.action !== "reverted" ? `. ${e.reason}` : ""}
          </div>
        </li>
      ))}
    </ol>
  );
}

function fmt(v, field) {
  if (v === null || v === undefined || v === "") return "blank";
  return field === "address" ? v : formatAmount(Number(v));
}
