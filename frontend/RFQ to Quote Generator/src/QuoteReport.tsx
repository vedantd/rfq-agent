import { useEffect, useState } from "react";
import Icon from "./Icon";
import { money, type Quote, type RFQ } from "./api";

// Final quote report: a modal over the page (same style as the drop window), shown when a quote is drafted.
// Everything comes from the draft-quote response plus the RFQ's analyzed lines.

export default function QuoteReport({ quote, rfq, onClose }: { quote: Quote; rfq: RFQ | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const lineOf = (id: string) => rfq?.lines.find((l) => l.id === id);
  const created = new Date(quote.created_at);
  const vsBenchmark = (pct?: number | null) =>
    pct == null ? "—" : pct >= 0 ? `${pct}% below` : `${Math.abs(pct)}% above`;

  return (
    <div className="drop-overlay report-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label={`Quote ${quote.id}`}>
      <div className="report" onClick={(e) => e.stopPropagation()}>
        <header className="report-head">
          <div>
            <div className="eyebrow"><span className="status-pulse" />{quote.status.replace(/_/g, " ").toUpperCase()}</div>
            <h2>Quote {quote.id}</h2>
            <span>{[quote.buyer_id && `For ${quote.buyer_id}`, quote.buyer_email, `RFQ ${quote.rfq_id}`, created.toLocaleString()].filter(Boolean).join(" · ")}</span>
          </div>
          <button className="icon-button" aria-label="Close report" onClick={onClose}>✕</button>
        </header>

        <section className="report-totals">
          <div><span>Grand total</span><strong>{money(quote.grand_total_usd)}</strong></div>
          <div><span>Lines</span><strong>{quote.lines.length}</strong></div>
          <div><span>Currency</span><strong>{quote.currency}</strong></div>
          <div><span>Ready to send</span><strong className={quote.ready_to_send ? "ok" : "warn"}>{quote.ready_to_send ? "Yes" : "No · demo data"}</strong></div>
        </section>

        {quote.warnings.length > 0 && <div className="report-warning"><Icon name="shield" size={14} />{quote.warnings.join(" ")}</div>}

        <div className="report-table-wrap">
          <table className="report-table">
            <thead>
              <tr><th>#</th><th>Item</th><th className="num">Qty</th><th className="num">Unit price</th><th className="num">Line total</th><th>Vs benchmark</th><th>Compliance</th></tr>
            </thead>
            <tbody>
              {quote.lines.map((q, i) => {
                const l = lineOf(q.line_id);
                return (
                  <tr key={q.line_id}>
                    <td>{String(i + 1).padStart(2, "0")}</td>
                    <td><strong>{q.description}</strong><span>{q.sku}{q.standard ? ` · ${q.standard}` : ""}{q.certifications?.length ? ` · ${q.certifications.join(", ")}` : ""}</span></td>
                    <td className="num">{q.quantity}</td>
                    <td className="num">{money(q.unit_price_usd)}</td>
                    <td className="num"><strong>{money(q.line_total_usd)}</strong></td>
                    <td>{vsBenchmark(l?.pricing?.below_benchmark_pct)}<span>{l?.pricing ? `benchmark ${money(l.pricing.benchmark_unit_usd)}` : ""}</span></td>
                    <td>{l?.compliance.status === "pass" ? "Pass" : l?.compliance.status ? l.compliance.status.replace(/_/g, " ") : "—"}<span>{l?.compliance.country_of_origin ? `origin ${l.compliance.country_of_origin}` : ""}</span></td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr><td colSpan={4}>Total</td><td className="num"><strong>{money(quote.grand_total_usd)}</strong></td><td colSpan={2} /></tr>
            </tfoot>
          </table>
        </div>

        {rfq && (
          <section className="report-notes">
            <strong>How these prices were set</strong>
            {quote.lines.map((q, i) => {
              const p = lineOf(q.line_id)?.pricing;
              return p ? <p key={q.line_id}>Line {i + 1}: {p.explanation}</p> : null;
            })}
          </section>
        )}

        <footer className="report-actions">
          <button className="secondary-button" onClick={async () => {
            try { await navigator.clipboard.writeText(JSON.stringify(quote, null, 2)); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard refused */ }
          }}><Icon name="document" size={15} />{copied ? "Copied" : "Copy quote JSON"}</button>
          <button className="secondary-button" onClick={() => window.print()}><Icon name="download" size={15} />Print / save PDF</button>
          <button className="primary-button" onClick={onClose}>Done</button>
        </footer>
      </div>
    </div>
  );
}
