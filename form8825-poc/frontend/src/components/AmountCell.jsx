import { useEffect, useRef, useState } from "react";
import { formatAmount, parseAmount } from "../api";

/**
 * One amount on the form. Click (or Enter) to edit; Enter saves, Escape cancels.
 * `check` is the validation result for total lines (2c, 18, 19, 20a, 20b, 23).
 */
export default function AmountCell({ line, check, onSave, onRevert, testId }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef(null);
  const busy = useRef(false); // Enter and blur can both fire; save once

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  if (!line) return <td className="cell cell-empty" />;

  const start = () => {
    setDraft(line.current_value === null ? "" : formatAmount(line.current_value));
    setError(null);
    setEditing(true);
  };

  const commit = async () => {
    if (busy.current) return;
    const parsed = parseAmount(draft);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    if (parsed.value === line.current_value) {
      setEditing(false);
      return;
    }
    busy.current = true;
    setSaving(true);
    try {
      await onSave(line, parsed.value);
      setEditing(false);
    } catch (e) {
      setError(e.message);
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  const failing = check?.status === "fail";
  const classes = [
    "cell",
    line.is_manual && "cell-manual",
    line.needs_review && !line.is_manual && "cell-review",
    failing && "cell-fail",
    line.section === "reserved" && "cell-reserved",
  ]
    .filter(Boolean)
    .join(" ");

  const title = [
    line.is_manual && `Extracted value: ${formatAmount(line.extracted_value) || "blank"}`,
    line.source && `Read from ${line.source}${line.confidence != null && line.source === "ocr" ? ` (${Math.round(line.confidence * 100)}% confidence)` : ""}`,
    failing && `Components add up to ${formatAmount(check.expected)}`,
  ]
    .filter(Boolean)
    .join("\n");

  if (editing) {
    return (
      <td className={classes}>
        <input
          ref={inputRef}
          className="cell-input"
          data-testid={`${testId}-input`}
          aria-label={`${line.label}, new value`}
          aria-invalid={!!error}
          value={draft}
          disabled={saving}
          inputMode="numeric"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") setEditing(false);
          }}
          onBlur={commit}
        />
        {error && (
          <div className="cell-error" role="alert" data-testid={`${testId}-error`}>
            {error}
          </div>
        )}
      </td>
    );
  }

  return (
    <td className={classes} title={title || undefined}>
      <div className="cell-row">
        {line.is_manual && (
          <button
            type="button"
            className="revert"
            data-testid={`${testId}-revert`}
            aria-label={`Revert ${line.label} to extracted value`}
            onClick={() => onRevert(line)}
          >
            ↺
          </button>
        )}
        <button
          type="button"
          className="cell-value"
          data-testid={testId}
          aria-label={`${line.label}: ${formatAmount(line.current_value) || "blank"}. Edit`}
          onClick={start}
        >
          {formatAmount(line.current_value)}
        </button>
        {check && (
          <span
            className={`tick tick-${check.status}`}
            data-testid={`${testId}-check`}
            aria-label={check.status === "pass" ? "Ties out" : check.message}
          >
            {check.status === "pass" ? "✓" : check.status === "fail" ? "✗" : "?"}
          </span>
        )}
      </div>
      {failing && <div className="cell-expected">should be {formatAmount(check.expected)}</div>}
    </td>
  );
}
