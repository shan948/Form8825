import { useCallback, useEffect, useRef, useState } from "react";
import { api, formatAmount, formatDate } from "./api";
import FormGrid from "./components/FormGrid";
import { HistoryPanel, SummaryPanel } from "./components/Panels";

export default function App() {
  const [docs, setDocs] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [doc, setDoc] = useState(null);
  const [history, setHistory] = useState([]);
  const [notice, setNotice] = useState(null); // {kind: "error"|"info", text}
  const [uploading, setUploading] = useState(false);

  const refreshList = useCallback(async () => {
    try {
      setDocs(await api.listDocuments());
    } catch (e) {
      setNotice({ kind: "error", text: `Could not reach the API: ${e.message}` });
    }
  }, []);

  const loadDoc = useCallback(async (id) => {
    if (id == null) return;
    const [d, h] = await Promise.all([api.getDocument(id), api.getHistory(id)]);
    setDoc(d);
    setHistory(h);
  }, []);

  useEffect(() => {
    refreshList();
  }, [refreshList]);

  useEffect(() => {
    if (selectedId != null) loadDoc(selectedId).catch((e) => setNotice({ kind: "error", text: e.message }));
    else setDoc(null);
  }, [selectedId, loadDoc]);

  const upload = async (file) => {
    if (!file) return;
    setUploading(true);
    setNotice(null);
    try {
      const d = await api.upload(file);
      await refreshList();
      setSelectedId(d.id);
      setNotice(
        d.duplicate
          ? { kind: "info", text: `${file.name} was already uploaded; showing the existing extraction.` }
          : { kind: "info", text: `Extracted ${d.properties.length} ${d.properties.length === 1 ? "property" : "properties"} from ${file.name}.` },
      );
    } catch (e) {
      setNotice({ kind: "error", text: `${file.name} could not be extracted: ${e.message}` });
      await refreshList();
      if (e.documentId) setSelectedId(e.documentId); // show the recorded failure
    } finally {
      setUploading(false);
    }
  };

  const afterChange = async () => {
    await Promise.all([loadDoc(selectedId), refreshList()]);
  };

  const saveLine = async (line, value) => {
    try {
      await api.updateLine(line.id, value, line.version, "Manual correction");
      setNotice(null);
    } catch (e) {
      if (e.status === 409) {
        await afterChange();
        setNotice({ kind: "error", text: "Someone else changed that line. The latest values are shown; make your change again." });
        return;
      }
      throw e;
    }
    await afterChange();
  };

  const revertLine = async (line) => {
    await api.revertLine(line.id);
    await afterChange();
  };

  const saveAddress = async (property, address) => {
    await api.updateAddress(property.id, address);
    await afterChange();
  };

  const remove = async () => {
    if (!doc || !window.confirm(`Delete ${doc.filename} and its change history?`)) return;
    await api.deleteDocument(doc.id);
    setSelectedId(null);
    await refreshList();
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-form">Form</span>
          <span className="brand-number">8825</span>
          <span className="brand-sub">Rental real estate review</span>
        </div>
        <UploadButton onFile={upload} busy={uploading} />
        <nav aria-label="Uploaded returns">
          {docs.length === 0 ? (
            <p className="muted small">Uploaded returns appear here.</p>
          ) : (
            <ul className="doc-list" data-testid="doc-list">
              {docs.map((d) => (
                <li key={d.id}>
                  <button
                    type="button"
                    className={`doc-item ${d.id === selectedId ? "active" : ""}`}
                    aria-current={d.id === selectedId ? "true" : undefined}
                    onClick={() => setSelectedId(d.id)}
                    data-testid={`doc-${d.id}`}
                  >
                    <span className="doc-name">{d.filename}</span>
                    <span className="doc-meta">
                      {d.status === "failed" ? (
                        <span className="badge badge-fail">Not extracted</span>
                      ) : (
                        <>
                          <StatusBadge status={d.validation_status} />
                          {d.property_count} {d.property_count === 1 ? "property" : "properties"}
                          {d.manual_changes > 0 && `, ${d.manual_changes} ${d.manual_changes === 1 ? "edit" : "edits"}`}
                        </>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>
      </aside>

      <main className="main">
        {notice && (
          <div className={`notice notice-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"} data-testid="notice">
            {notice.text}
            <button type="button" className="notice-close" aria-label="Dismiss" onClick={() => setNotice(null)}>×</button>
          </div>
        )}
        {!doc ? (
          <EmptyState onFile={upload} busy={uploading} />
        ) : doc.status === "failed" ? (
          <FailedDoc doc={doc} onDelete={remove} />
        ) : (
          <DocumentView
            doc={doc}
            history={history}
            onSave={saveLine}
            onRevert={revertLine}
            onAddress={saveAddress}
            onDelete={remove}
          />
        )}
      </main>
    </div>
  );
}

function DocumentView({ doc, history, onSave, onRevert, onAddress, onDelete }) {
  const v = doc.validation;
  const fails = v.checks.filter((c) => c.status === "fail");
  return (
    <div className="doc">
      <header className="doc-header">
        <div>
          <h1 data-testid="taxpayer">{doc.taxpayer_name || "Unnamed taxpayer"}</h1>
          <p className="doc-sub">
            EIN {doc.ein || "not found"}. {doc.filename}, read from {methodText(doc.extraction_method)}, uploaded {formatDate(doc.created_at)}.
          </p>
        </div>
        <div className="doc-actions">
          <a className="btn" href={api.fileUrl(doc.id)} target="_blank" rel="noreferrer">Open PDF</a>
          <a className="btn btn-primary" href={api.exportUrl(doc.id)} data-testid="export">Download JSON</a>
          <button type="button" className="btn btn-quiet" onClick={onDelete}>Delete</button>
        </div>
      </header>

      <section className={`verdict verdict-${v.status}`} data-testid="verdict" aria-live="polite">
        <div>
        {v.status === "fail" ? (
          <>
            <strong>{fails.length} {fails.length === 1 ? "total doesn't" : "totals don't"} add up.</strong>
            <ul>
              {fails.map((c, i) => (
                <li key={i}>
                  {c.property ? `Property ${c.property}, ` : "Form, "}line {c.line}: reported {formatAmount(c.actual)}, components add up to {formatAmount(c.expected)}.
                </li>
              ))}
            </ul>
          </>
        ) : v.status === "warn" ? (
          <strong>Totals add up, but some lines were blank on the form and were computed.</strong>
        ) : (
          <strong>Every total adds up.</strong>
        )}
        </div>
        <span className="verdict-count">{v.passed} of {v.checks.length} checks pass</span>
      </section>

      {doc.warnings.length > 0 && (
        <details className="warnings">
          <summary>{doc.warnings.length} extraction {doc.warnings.length === 1 ? "note" : "notes"} to review</summary>
          <ul>{doc.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </details>
      )}

      <div className="doc-body">
        <div className="sheet">
          <p className="hint">Click any amount to correct it. Changed amounts are marked in red pencil; ↺ restores the extracted value.</p>
          <FormGrid doc={doc} onSave={onSave} onRevert={onRevert} onAddress={onAddress} />
          <h2 className="sheet-title">Form totals</h2>
          <SummaryPanel doc={doc} onSave={onSave} onRevert={onRevert} />
        </div>
        <aside className="history-panel" aria-label="Change history">
          <h2>Change history</h2>
          <HistoryPanel entries={history} />
        </aside>
      </div>
    </div>
  );
}

function methodText(method) {
  const names = { acroform: "form fields", text: "the text layer", ocr: "OCR" };
  return (method || "").split("+").map((m) => names[m] ?? m).join(" and ") || "unknown source";
}

function StatusBadge({ status }) {
  const text = { pass: "Adds up", warn: "Check", fail: "Mismatch" }[status] ?? status;
  return <span className={`badge badge-${status}`}>{text}</span>;
}

function UploadButton({ onFile, busy }) {
  const ref = useRef(null);
  return (
    <>
      <input
        ref={ref}
        type="file"
        accept="application/pdf,.pdf"
        hidden
        data-testid="file-input"
        onChange={(e) => {
          onFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <button type="button" className="btn btn-primary btn-block" disabled={busy} onClick={() => ref.current?.click()}>
        {busy ? "Extracting…" : "Upload 8825 PDF"}
      </button>
    </>
  );
}

function EmptyState({ onFile, busy }) {
  const [over, setOver] = useState(false);
  return (
    <div
      className={`dropzone ${over ? "over" : ""}`}
      data-testid="dropzone"
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        onFile(e.dataTransfer.files?.[0]);
      }}
    >
      <h1>{busy ? "Reading the form…" : "Drop a Form 8825 PDF here"}</h1>
      <p>
        Fillable, flattened and scanned returns all work. Each property's income and expenses are extracted, the totals are checked,
        and you can correct any amount before exporting JSON.
      </p>
    </div>
  );
}

function FailedDoc({ doc, onDelete }) {
  return (
    <div className="failed" data-testid="failed-doc">
      <h1>{doc.filename} couldn't be extracted</h1>
      <p>{doc.error_message}</p>
      <p className="muted small">Error code: {doc.error_code}</p>
      <button type="button" className="btn" onClick={onDelete}>Remove from list</button>
    </div>
  );
}
