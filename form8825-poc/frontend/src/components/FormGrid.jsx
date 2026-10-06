import { useState } from "react";
import AmountCell from "./AmountCell";

const CHECKED_LINES = new Set(["2c", "18", "19"]);
const SECTION_TITLES = { "2a": "Rental real estate income", "3": "Rental real estate expenses" };

/** Lines 2a-19 laid out like the printed form: line box, description, one column per property. */
export default function FormGrid({ doc, onSave, onRevert, onAddress }) {
  const props = doc.properties;
  const rows = props[0]?.lines ?? [];
  const checkFor = (label, code) =>
    doc.validation.checks.find((c) => c.scope === "property" && c.property === label && c.line === code);

  return (
    <div className="grid-scroll">
      <table className="form-grid" data-testid="form-grid">
        <thead>
          <tr>
            <th className="col-line" scope="col">Line</th>
            <th className="col-desc" scope="col">Description</th>
            {props.map((p) => (
              <th key={p.id} scope="col" className="col-prop" data-testid={`prop-head-${p.label}`}>
                <span className="prop-letter">{p.label}</span>
                <AddressEditor property={p} onSave={onAddress} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <FormRow key={row.line_code} row={row} props={props} checkFor={checkFor} onSave={onSave} onRevert={onRevert} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FormRow({ row, props, checkFor, onSave, onRevert }) {
  const code = row.line_code;
  const isTotal = row.section === "total";
  return (
    <>
      {SECTION_TITLES[code] && (
        <tr className="section-row">
          <th colSpan={2 + props.length} scope="rowgroup">{SECTION_TITLES[code]}</th>
        </tr>
      )}
      <tr className={`row row-${row.section}`} data-testid={`row-${code}`}>
        <td className="col-line"><span className="line-box">{code}</span></td>
        <th scope="row" className="col-desc">{row.label}</th>
        {props.map((p) => {
          const line = p.lines.find((l) => l.line_code === code);
          return (
            <AmountCell
              key={p.id}
              line={line}
              testId={`cell-${p.label}-${code}`}
              check={isTotal && CHECKED_LINES.has(code) ? checkFor(p.label, code) : undefined}
              onSave={onSave}
              onRevert={onRevert}
            />
          );
        })}
      </tr>
    </>
  );
}

function AddressEditor({ property, onSave }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(property.address ?? "");
  const changed = property.address !== property.extracted_address;

  if (editing) {
    const done = async (save) => {
      if (save && draft !== property.address) await onSave(property, draft);
      setEditing(false);
    };
    return (
      <input
        className="address-input"
        aria-label={`Address of property ${property.label}`}
        data-testid={`address-${property.label}-input`}
        value={draft}
        autoFocus
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") done(true);
          if (e.key === "Escape") done(false);
        }}
        onBlur={() => done(true)}
      />
    );
  }
  return (
    <button
      type="button"
      className={`address ${changed ? "cell-manual" : ""}`}
      data-testid={`address-${property.label}`}
      title={changed ? `Extracted: ${property.extracted_address ?? "blank"}` : "Edit address"}
      onClick={() => {
        setDraft(property.address ?? "");
        setEditing(true);
      }}
    >
      {property.address || "Add address"}
    </button>
  );
}
