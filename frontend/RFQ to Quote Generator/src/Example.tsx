import { useState, type ReactNode } from "react";
import Icon, { type IconName } from "./Icon";

// Shuang's original Figma Make design, unchanged, shown with its example data until a real RFQ is processed.

const lineItems = [
  { line: "01", input: "304 SS sheet 16ga 4x8", match: "Stainless steel sheet", spec: "ASTM A240 · 304 · 0.0598 in", qty: "24 sheets", unit: "$138.40", total: "$3,321.60", confidence: 98, status: "Verified" },
  { line: "02", input: "A36 PL 1/4 60 x 120", match: "Carbon steel plate", spec: "ASTM A36 · 0.250 in", qty: "10 plates", unit: "$286.15", total: "$2,861.50", confidence: 96, status: "Verified" },
  { line: "03", input: "2in sched 40 pipe, 316L", match: "Stainless pipe", spec: "ASTM A312 · 316L · Sch 40", qty: "400 ft", unit: "$18.72", total: "$7,488.00", confidence: 87, status: "Review" },
  { line: "04", input: "Al angle 6061 2x2x.125", match: "Aluminum equal angle", spec: "ASTM B221 · 6061-T6", qty: "120 ft", unit: "$4.94", total: "$592.80", confidence: 72, status: "Question" },
];

export default function Example({ assistant, onNew }: { assistant: ReactNode; onNew: () => void }) {
  const [activeTab, setActiveTab] = useState("Line items");
  const [selectedLine, setSelectedLine] = useState("03");
  const fileName = "RudCo_RFQ_1048.pdf";

  return (
    <>
      <section className="title-row">
        <div>
          <div className="eyebrow"><span className="status-pulse" />PROCESSING COMPLETE</div>
          <div className="page-title" role="heading" aria-level={1}>RFQ-1048 <span>Northline Fabrication</span></div>
          <div className="subtitle">Received via email · Jun 18, 2025 at 9:42 AM · 4 line items</div>
        </div>
        <div className="title-actions">
          <button className="secondary-button"><Icon name="download" size={16} />Export</button>
          <button className="primary-button" onClick={onNew}>Review draft quote<Icon name="arrow" size={16} /></button>
        </div>
      </section>

      <section className="pipeline" aria-label="RFQ processing progress">
        {[
          ["Parse & normalize", "Completed in 4.2s", "check"],
          ["Catalog matching", "4 of 4 matched", "check"],
          ["Compliance", "3 verified · 1 review", "shield"],
          ["Price benchmark", "Within market range", "activity"],
          ["Quote ready", "Draft generated", "spark"],
        ].map(([title, sub, icon], index) => (
          <div className="pipeline-step" key={title}>
            <div className="step-icon"><Icon name={icon as IconName} size={16} /></div>
            <div><strong>{title}</strong><span>{sub}</span></div>
            {index < 4 && <div className="connector" />}
          </div>
        ))}
      </section>

      <div className="content-grid">
        <section className="work-panel">
          <div className="tabs">
            {["Line items", "Source document", "Activity"].map((tab) => (
              <button className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)} key={tab}>
                {tab}{tab === "Line items" && <span>4</span>}
              </button>
            ))}
            <button className="panel-menu" aria-label="More options"><Icon name="more" /></button>
          </div>

          {activeTab === "Line items" ? (
            <>
              <div className="table-head table-grid">
                <span>Original request</span><span>Normalized match & specification</span><span>Quantity</span><span>Quote</span><span>Confidence</span>
              </div>
              <div className="item-list">
                {lineItems.map((item) => (
                  <button className={`item-row table-grid ${selectedLine === item.line ? "selected" : ""}`} key={item.line} onClick={() => setSelectedLine(item.line)}>
                    <div className="original-cell"><span className="line-number">{item.line}</span><div><strong>{item.input}</strong><span>Line {Number(item.line)}</span></div></div>
                    <div className="match-cell"><strong>{item.match}</strong><span>{item.spec}</span><em><Icon name="check" size={11} />Catalog matched</em></div>
                    <div className="quantity-cell"><strong>{item.qty}</strong><span>Requested</span></div>
                    <div className="quote-cell"><strong>{item.total}</strong><span>{item.unit} / unit</span></div>
                    <div className="confidence-cell">
                      <div className={`confidence ${item.confidence < 80 ? "low" : item.confidence < 90 ? "medium" : ""}`}>{item.confidence}%</div>
                      <span className={`item-status ${item.status.toLowerCase()}`}>{item.status}</span>
                    </div>
                  </button>
                ))}
              </div>
              <div className="table-footer">
                <span><Icon name="spark" size={15} />Normalized via Nicrron Gateway</span>
                <span>Last updated just now</span>
              </div>
            </>
          ) : activeTab === "Source document" ? (
            <div className="document-preview">
              <div className="file-card"><Icon name="document" size={30} /><div><strong>{fileName}</strong><span>PDF document · 2 pages</span></div><button className="secondary-button">Open document</button></div>
              <div className="document-lines">{Array.from({ length: 8 }).map((_, i) => <span key={i} className={i === 2 || i === 5 ? "short" : ""} />)}</div>
            </div>
          ) : (
            <div className="activity-list">
              {[
                ["Draft quote generated", "Pricing and terms prepared for review", "Just now"],
                ["Compliance check completed", "Country of origin flag on line 03", "12 sec ago"],
                ["Catalog matching completed", "4 items matched against 18,400 SKUs", "18 sec ago"],
                ["RFQ received", fileName, "32 sec ago"],
              ].map(([title, detail, time]) => <div className="activity-row" key={title}><div className="activity-dot"><Icon name="check" size={13} /></div><div><strong>{title}</strong><span>{detail}</span></div><time>{time}</time></div>)}
            </div>
          )}
        </section>

        <aside className="right-panel">
          {assistant}

          <div className="summary-card">
            <div className="card-heading"><div><span>Draft quote</span><strong>$14,263.90</strong></div><span className="draft-badge">DRAFT</span></div>
            <div className="summary-lines">
              <div><span>Materials subtotal</span><strong>$14,263.90</strong></div>
              <div><span>Freight estimate</span><strong>Calculated at checkout</strong></div>
              <div><span>Lead time</span><strong>8–12 business days</strong></div>
              <div><span>Valid until</span><strong>Jul 18, 2025</strong></div>
            </div>
            <div className="margin-box"><div><span>Estimated margin</span><strong>18.4%</strong></div><div className="margin-track"><span /></div><small>2.4% above your target</small></div>
            <button className="primary-button full" onClick={onNew}>Review & send quote<Icon name="arrow" size={16} /></button>
            <button className="text-button">Edit pricing & terms</button>
          </div>

          <div className="review-card">
            <div className="card-title"><div><Icon name="spark" size={17} />Needs your attention</div><span>1</span></div>
            <div className="attention-content">
              <div className="attention-head"><span className="amber-icon"><Icon name="clock" size={15} /></span><div><strong>Clarification recommended</strong><span>Line 04 · 72% confidence</span></div></div>
              <p>The requested temper is not specified for the aluminum angle.</p>
              <div className="question-box"><span>Suggested question</span><p>“Should we quote the aluminum angle in 6061-T6 temper?”</p></div>
              <div className="attention-actions"><button className="secondary-button">Edit</button><button className="dark-button">Add to email</button></div>
            </div>
          </div>

          <div className="audit-card">
            <div className="audit-icon"><Icon name="shield" size={17} /></div>
            <div><strong>Fully auditable</strong><span>18 reasoning steps and sources logged</span></div>
            <button aria-label="View audit"><Icon name="chevron" size={16} /></button>
          </div>
        </aside>
      </div>
    </>
  );
}
