import { useEffect } from "react";
import Icon from "./Icon";
import { money, type CatalogItem, type Line, type RFQ } from "./api";

// Review pop-up shown when the pipeline reaches "Quote ready": summary, every line, and the
// clarifying questions answerable in place. Draft quote hands over to the final QuoteReport.

const FIELD_LABEL: Record<string, string> = {
  material: "Material", form: "Form", grade: "Grade", thickness_in: "Thickness (in)", width_in: "Width (in)",
  length_in: "Length (in)", quantity: "Quantity", sku: "Preferred SKU", standard_required: "Standard",
};
const STATUS: Record<string, { text: string; cls: string }> = {
  extracted: { text: "Extracted", cls: "review" }, ready_for_approval: { text: "Ready", cls: "verified" },
  approved: { text: "Approved", cls: "verified" }, needs_clarification: { text: "Question", cls: "question" },
  needs_review: { text: "Review", cls: "review" }, blocked_compliance: { text: "Blocked", cls: "question" },
};

// ---- answer options from the catalog -------------------------------------------------------------
// Seed SKUs say material "stainless_steel"; dataset SKUs say material_family "stainless steel".
const num = (v: unknown) => (v === null || v === undefined || v === "" ? null : Number(v));
const matOf = (it: CatalogItem) => (it.material || it.material_family || "").toLowerCase().replace(/\s+/g, "_");
const formOf = (it: CatalogItem) => (it.form || it.shape || "").toLowerCase();
const sameSize = (it: CatalogItem, l: Line) => {
  const a = [num(it.width_in), num(it.length_in)].sort(), b = [l.width_in ?? null, l.length_in ?? null].sort();
  return a[0] === b[0] && a[1] === b[1];
};

export interface Option { label: string; set: Record<string, string> }

/** Distinct values of `field` among catalog items that fit everything already known about the line. */
export function optionsFor(field: string, l: Line, catalog: CatalogItem[]): Option[] {
  const fits = (it: CatalogItem, strict: boolean) =>
    (field === "material" || !l.material || matOf(it) === l.material.toLowerCase()) &&
    (field === "form" || !l.form || formOf(it) === l.form.toLowerCase()) &&
    (field === "grade" || !l.grade || String(it.grade || "").toUpperCase().startsWith(String(l.grade).toUpperCase())) &&
    (!strict || field === "thickness_in" || l.thickness_in == null || Math.abs((num(it.thickness_in) ?? -9) - l.thickness_in) <= 0.003) &&
    (!strict || field === "width_in" || field === "length_in" || l.width_in == null || l.length_in == null || sameSize(it, l));
  let pool = catalog.filter((it) => fits(it, true));
  if (!pool.length) pool = catalog.filter((it) => fits(it, false));   // relax size/thickness if nothing fits
  const seen = new Map<string, Option>();
  for (const it of pool) {
    let o: Option | null = null;
    if (field === "grade" && it.grade) o = { label: String(it.grade), set: { grade: String(it.grade) } };
    else if (field === "thickness_in" && num(it.thickness_in) != null) {
      const t = num(it.thickness_in)!;
      o = { label: `${t} in${it.gauge ? ` (${it.gauge} ga)` : ""}`, set: { thickness_in: String(t) } };
    } else if ((field === "width_in" || field === "length_in") && num(it.width_in) != null && num(it.length_in) != null)
      o = { label: `${num(it.width_in)} × ${num(it.length_in)} in`, set: { width_in: String(num(it.width_in)), length_in: String(num(it.length_in)) } };
    else if (field === "material" && matOf(it)) o = { label: matOf(it).replace(/_/g, " "), set: { material: matOf(it) } };
    else if (field === "form" && formOf(it)) o = { label: formOf(it), set: { form: formOf(it) } };
    if (o && !seen.has(o.label)) seen.set(o.label, o);
  }
  const out = [...seen.values()];
  const n = (o: Option) => parseFloat(o.label);
  return out.sort((a, b) => (isNaN(n(a)) || isNaN(n(b)) ? a.label.localeCompare(b.label) : n(a) - n(b))).slice(0, 12);
}

export interface ReviewProps {
  rfq: RFQ;
  catalog: CatalogItem[];
  fileName: string | null;
  busy: string | null;
  answers: Record<string, string>;
  setAnswer: (key: string, value: string) => void;
  answerable: Set<string>;
  numeric: Set<string>;
  onApply: (line: Line) => void;
  onApprove: () => void;
  onDraft: () => void;
  onCopyEmail: () => void;
  onClose: () => void;
}

export default function ReviewModal(p: ReviewProps) {
  const { rfq } = p;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") p.onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [p.onClose]);

  const lines = rfq.lines;
  const priced = lines.filter((l) => l.pricing);
  const total = priced.reduce((s, l) => s + (l.pricing?.line_total_usd || 0), 0);
  const ready = lines.filter((l) => l.status === "ready_for_approval");
  const approved = lines.filter((l) => l.status === "approved");
  const withQuestions = lines.filter((l) => l.clarifications.length);
  const blocked = lines.filter((l) => l.status === "blocked_compliance");
  const allApproved = lines.length > 0 && approved.length === lines.length;

  return (
    <div className="drop-overlay report-overlay" onClick={p.onClose} role="dialog" aria-modal="true" aria-label="RFQ review">
      <div className="report" onClick={(e) => e.stopPropagation()}>
        <header className="report-head">
          <div>
            <div className="eyebrow"><span className="status-pulse" />{withQuestions.length ? "NEEDS YOUR ANSWERS" : allApproved ? "READY TO QUOTE" : "READY FOR APPROVAL"}</div>
            <h2>RFQ summary</h2>
            <span>{[rfq.rfq_id, rfq.buyer_id, p.fileName, `${rfq.line_count} lines`, rfq.gateway?.model].filter(Boolean).join(" · ")}</span>
          </div>
          <button className="icon-button" aria-label="Close summary" onClick={p.onClose}>✕</button>
        </header>

        <section className="report-totals">
          <div><span>Priced so far</span><strong>{money(total)}</strong></div>
          <div><span>Ready / approved</span><strong>{ready.length} / {approved.length}</strong></div>
          <div><span>Need answers</span><strong className={withQuestions.length ? "warn" : "ok"}>{withQuestions.length}</strong></div>
          <div><span>Compliance blocked</span><strong className={blocked.length ? "warn" : "ok"}>{blocked.length}</strong></div>
        </section>

        <div className="report-table-wrap">
          <table className="report-table">
            <thead><tr><th>#</th><th>Request</th><th>Match</th><th className="num">Qty</th><th className="num">Line total</th><th>Status</th></tr></thead>
            <tbody>
              {lines.map((l, i) => {
                const st = STATUS[l.status] || { text: l.status, cls: "review" };
                return (
                  <tr key={l.id}>
                    <td>{String(i + 1).padStart(2, "0")}</td>
                    <td><strong>{l.raw_text}</strong></td>
                    <td>{l.match ? l.match.sku : "—"}<span>{l.match ? l.match.supplier_standard : l.blockers.join(", ").replace(/_in/g, "")}</span></td>
                    <td className="num">{l.quantity ?? "?"}</td>
                    <td className="num">{money(l.pricing?.line_total_usd)}</td>
                    <td><span className={`item-status ${st.cls}`}>{st.text}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {withQuestions.length > 0 && (
          <section className="review-questions">
            <strong>Clarifying questions</strong>
            <p className="muted">Answer what you know; the line is re-checked against the catalog right away. Anything you can't answer goes to the buyer.</p>
            {withQuestions.map((l) => {
              const i = lines.indexOf(l);
              const canAnswer = l.clarifications.some((c) => p.answerable.has(c.field));
              return (
                <div className="review-line" key={l.id}>
                  <div className="review-line-head"><span className="line-number">{String(i + 1).padStart(2, "0")}</span><strong>{l.raw_text}</strong></div>
                  <div className="review-fields">
                    {l.clarifications.map((c) => (
                      <label key={c.field} className="review-field">
                        <span>{c.question}</span>
                        {p.answerable.has(c.field) && (() => {
                          const opts = optionsFor(c.field, l, p.catalog);
                          return opts.length > 0 && (
                            <div className="answer-options" role="group" aria-label={`Options for ${FIELD_LABEL[c.field] || c.field}`}>
                              {opts.map((o) => {
                                const on = Object.entries(o.set).every(([f, v]) => p.answers[`${l.id}.${f}`] === v);
                                return <button type="button" key={o.label} className={`answer-chip ${on ? "on" : ""}`}
                                  onClick={(e) => { e.preventDefault(); Object.entries(o.set).forEach(([f, v]) => p.setAnswer(`${l.id}.${f}`, v)); }}>{o.label}</button>;
                              })}
                            </div>
                          );
                        })()}
                        {p.answerable.has(c.field)
                          ? <input type={p.numeric.has(c.field) ? "number" : "text"} step="any" placeholder={FIELD_LABEL[c.field] || c.field}
                              value={p.answers[`${l.id}.${c.field}`] || ""} onChange={(e) => p.setAnswer(`${l.id}.${c.field}`, e.target.value)}
                              onKeyDown={(e) => { if (e.key === "Enter") p.onApply(l); }} />
                          : <em>Needs the buyer: include it in the email.</em>}
                      </label>
                    ))}
                  </div>
                  {canAnswer && <div className="review-apply"><button className="dark-button" onClick={() => p.onApply(l)} disabled={!!p.busy}>Apply answers</button></div>}
                </div>
              );
            })}
          </section>
        )}

        <footer className="report-actions">
          {withQuestions.length > 0 && <button className="secondary-button" onClick={p.onCopyEmail} disabled={!!p.busy}><Icon name="document" size={15} />Copy buyer email</button>}
          <button className="secondary-button" onClick={p.onClose}>Close</button>
          {!allApproved && <button className="primary-button" onClick={p.onApprove} disabled={!!p.busy || !ready.length}>Approve {ready.length} ready line{ready.length === 1 ? "" : "s"}</button>}
          <button className="primary-button" onClick={p.onDraft} disabled={!!p.busy || !allApproved}
            title={allApproved ? "" : "Every line must be answered and approved first"}>Draft quote<Icon name="arrow" size={15} /></button>
        </footer>
        {p.busy && <div className="review-busy">{p.busy}</div>}
      </div>
    </div>
  );
}
