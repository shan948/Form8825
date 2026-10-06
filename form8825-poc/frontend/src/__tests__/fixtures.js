// Minimal API payloads shaped like the FastAPI responses.
const line = (id, code, label, section, value, extra = {}) => ({
  id, line_code: code, field_key: code, section, label, extracted_value: value, current_value: value,
  raw_text: value == null ? null : String(value), source: value == null ? null : "acroform",
  confidence: 1, needs_review: false, is_manual: false, version: 1, ...extra,
});

export function makeDoc({ gross = 1000, expensesTotal = 300, manual = false } = {}) {
  const lines = [
    line(1, "2a", "Gross rents", "income", gross, manual ? { extracted_value: 900, is_manual: true } : {}),
    line(2, "2b", "Other income", "income", null),
    line(3, "2c", "Total rental real estate income (2a + 2b)", "total", 1000),
    line(4, "3", "Advertising", "expense", 300),
    line(5, "18", "Total expenses (lines 3 through 17)", "total", expensesTotal),
    line(6, "19", "Income or (loss) (2c - 18)", "total", 700),
  ];
  const checks = [
    { scope: "property", property: "A", rule: "2c", line: "2c", expected: gross, actual: 1000, difference: 1000 - gross, status: gross === 1000 ? "pass" : "fail", message: "" },
    { scope: "property", property: "A", rule: "18", line: "18", expected: 300, actual: expensesTotal, difference: expensesTotal - 300, status: expensesTotal === 300 ? "pass" : "fail", message: "" },
    { scope: "property", property: "A", rule: "19", line: "19", expected: gross - 300, actual: 700, difference: 0, status: gross - 300 === 700 ? "pass" : "fail", message: "" },
  ];
  const failed = checks.filter((c) => c.status === "fail").length;
  return {
    id: 1, filename: "sample.pdf", sha256: "x", status: "extracted", error_code: null, error_message: null,
    taxpayer_name: "Test LLC", ein: "12-3456789", extraction_method: "acroform", page_count: 2,
    created_at: "2026-09-29T10:00:00",
    properties: [{ id: 10, label: "A", address: "4th st plaza", extracted_address: "4th st plaza", page: 1, lines, computed: { "2c": gross, 18: 300, 19: gross - 300 } }],
    summary_lines: [line(20, "20a", "Total rental income (all properties)", "summary", 1000)],
    grand_total_net_income: gross - 300,
    validation: { status: failed ? "fail" : "pass", passed: checks.length - failed, failed, warnings: 0, checks },
    warnings: [],
    duplicate: false,
  };
}

export const listItem = { id: 1, filename: "sample.pdf", status: "extracted", error_code: null, taxpayer_name: "Test LLC", property_count: 1, validation_status: "pass", grand_total_net_income: 700, manual_changes: 0, created_at: "2026-09-29T10:00:00" };
