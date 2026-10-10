import { useEffect } from "react";
import Icon from "./Icon";
import { money, type Line, type RFQ } from "./api";

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

export interface ReviewProps {
  rfq: RFQ;
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
