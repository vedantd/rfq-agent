import { useEffect, useRef, useState } from "react";
import Assistant from "./Assistant";
import Example from "./Example";
import Icon, { type IconName } from "./Icon";
import { api, ApiError, money, type Line, type Quote, type RFQ } from "./api";

const nav = [
  { label: "Overview", icon: "grid" as IconName },
  { label: "RFQ Inbox", icon: "inbox" as IconName },
  { label: "Catalog", icon: "cube" as IconName },
  { label: "Quotes", icon: "document" as IconName },
  { label: "Audit log", icon: "shield" as IconName },
];

const SAMPLE = `Hi team, please quote the following for Northline Fabrication:
1) 304 SS sheet 16ga 4x8, qty 24
2) Stainless sheet 4x8, 10 pcs (architect still finalizing the finish)
Mill certs required. Thanks!`;

const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  ready_for_approval: { text: "Ready", cls: "verified" },
  approved: { text: "Approved", cls: "verified" },
  needs_clarification: { text: "Question", cls: "question" },
  needs_review: { text: "Review", cls: "review" },
  blocked_compliance: { text: "Blocked", cls: "question" },
};

const FIELD_LABEL: Record<string, string> = {
  material: "Material", form: "Form", grade: "Grade", thickness_in: "Thickness (in)",
  width_in: "Width (in)", length_in: "Length (in)", quantity: "Quantity", sku: "Preferred SKU", standard_required: "Standard",
};
const NUMERIC = new Set(["thickness_in", "width_in", "length_in", "quantity"]);
const CLARIFY_FIELDS = new Set(["material", "form", "grade", "thickness_in", "width_in", "length_in", "quantity", "standard_required"]);

const spec = (l: Line) =>
  [l.match?.supplier_standard, l.grade, l.thickness_in != null ? `${l.thickness_in} in` : null,
    l.width_in && l.length_in ? `${l.width_in} x ${l.length_in}` : null].filter(Boolean).join(" · ");
const title = (l: Line) => [l.material, l.form].filter(Boolean).join(" ").replace(/_/g, " ") || "Not identified yet";

function App() {
  const [activeNav, setActiveNav] = useState("RFQ Inbox");
  const [activeTab, setActiveTab] = useState("Line items");
  const [rfq, setRfq] = useState<RFQ | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [selectedLine, setSelectedLine] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [sourceText, setSourceText] = useState(SAMPLE);
  const [buyer, setBuyer] = useState("Northline Fabrication");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [model, setModel] = useState<string>("");
  const [message, setMessage] = useState<{ id: number; text: string } | null>(null);
  const [composing, setComposing] = useState(false);   // false + no RFQ = Shuang's example screen
  const fileInput = useRef<HTMLInputElement>(null);
  const say = (text: string) => setMessage((m) => ({ id: (m?.id || 0) + 1, text }));

  useEffect(() => { api.health().then((h) => setModel(h?.gateway?.model || "")).catch(() => setModel("")); }, []);

  const lines = rfq?.lines || [];
  const priced = lines.filter((l) => l.pricing);
  const subtotal = priced.reduce((s, l) => s + (l.pricing?.line_total_usd || 0), 0);
  const open = lines.filter((l) => l.status === "needs_clarification" || l.status === "needs_review" || l.status === "blocked_compliance");
  const ready = lines.filter((l) => l.status === "ready_for_approval");
  const allApproved = lines.length > 0 && lines.every((l) => l.status === "approved");
  const current = lines.find((l) => l.id === selectedLine) || open[0] || lines[0];

  function announce(r: RFQ) {
    const pricedNow = r.lines.filter((l) => l.pricing);
    const total = pricedNow.reduce((s, l) => s + (l.pricing?.line_total_usd || 0), 0);
    const q = r.lines.filter((l) => l.clarifications.length);
    let t = `I read ${r.line_count} line${r.line_count === 1 ? "" : "s"} and priced ${pricedNow.length}, for ${money(total)}.`;
    if (q.length) t += ` Before I can quote the rest I need answers on ${q.length} line${q.length > 1 ? "s" : ""}. ${q[0].clarifications.map((c) => c.question).join(" ")}`;
    else t += " Nothing is unclear, so approve the lines and I'll draft the quote.";
    say(t);
  }

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label); setError(null);
    try { await fn(); }
    catch (e) {
      const msg = e instanceof ApiError ? `${e.message}${e.status === 502 || e.status === 503 ? " (the live AI gateway did not return a usable answer)" : ""}` : String(e);
      setError(msg); say(`That didn't work: ${msg}`);
    }
    setBusy(null);
  }

  const process = (file?: File) => run(file ? `Reading ${file.name}…` : "Reading the RFQ…", async () => {
    const r = file ? await api.uploadRfq(file, buyer || "buyer") : await api.createRfq(sourceText, buyer || "buyer", undefined, "email");
    if (file) setFileName(file.name);
    setRfq(r); setQuote(null); setAnswers({}); setComposing(false);
    setSelectedLine((r.lines.find((l) => l.clarifications.length) || r.lines[0])?.id || null);
    setActiveTab("Line items");
    announce(r);
  });

  const submitAnswers = (l: Line) => run("Updating the line…", async () => {
    const fields: Record<string, string | number> = {};
    for (const c of l.clarifications) {
      const v = (answers[`${l.id}.${c.field}`] || "").trim();
      if (!v || !CLARIFY_FIELDS.has(c.field)) continue;
      fields[c.field] = NUMERIC.has(c.field) ? Number(v) : v;
    }
    if (!Object.keys(fields).length) throw new Error("Type at least one answer first.");
    const updated = await api.clarify(rfq!.rfq_id, l.id, fields);
    const r = await api.getRfq(rfq!.rfq_id);
    setRfq(r);
    say(updated.pricing ? `Thanks. ${updated.raw_text} now matches ${updated.match?.sku} at ${money(updated.pricing.line_total_usd)}.`
      : `Still not enough to quote that line. ${updated.clarifications.map((c) => c.question).join(" ")}`);
  });

  const approveReady = () => run("Approving…", async () => {
    for (const l of ready) await api.approve(rfq!.rfq_id, l.id);
    const r = await api.getRfq(rfq!.rfq_id);
    setRfq(r);
    const left = r.lines.filter((l) => l.status !== "approved").length;
    say(left ? `Approved ${ready.length}. ${left} line${left > 1 ? "s" : ""} still need${left > 1 ? "" : "s"} an answer before I can draft the quote.` : "Everything is approved. I can draft the quote now.");
  });

  const draft = () => run("Drafting the quote…", async () => {
    const q = await api.draftQuote(rfq!.rfq_id);
    setQuote(q);
    say(`Quote ${q.id} is drafted: ${money(q.grand_total_usd)}. ${q.warnings.join(" ")}`);
  });

  const copyEmail = () => run("Drafting the buyer email…", async () => {
    const e = await api.emailDraft(rfq!.rfq_id);
    await navigator.clipboard.writeText(`Subject: ${e.subject}\n\n${e.body}`).catch(() => undefined);
    say("I copied the clarification email to your clipboard. It's a draft only; nothing was sent.");
  });

  const reset = () => { setRfq(null); setQuote(null); setFileName(null); setError(null); setSelectedLine(null); setComposing(true); say("Ready for a new RFQ. Paste it, or drop any file: PDF, photo, spreadsheet, Word or email."); };

  const steps: [string, string, IconName, boolean][] = rfq ? [
    ["Parse & normalize", `${rfq.gateway?.model || rfq.parser_mode}${rfq.gateway?.latency_ms ? ` · ${(rfq.gateway.latency_ms / 1000).toFixed(1)}s` : ""}`, "check", true],
    ["Catalog matching", `${lines.filter((l) => l.match).length} of ${lines.length} matched`, "check", lines.some((l) => l.match)],
    ["Compliance", `${lines.filter((l) => l.compliance.status === "pass").length} pass · ${lines.filter((l) => l.compliance.status === "blocked").length} blocked`, "shield", lines.some((l) => l.compliance.status !== "not_evaluated")],
    ["Price benchmark", priced.length ? `${priced.length} priced vs benchmark` : "Waiting on matches", "activity", priced.length > 0],
    ["Quote ready", quote ? quote.id : allApproved ? "All lines approved" : `${rfq.approved} of ${rfq.line_count} approved`, "spark", !!quote],
  ] : [];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><span /><span /><span /></div>
          <div className="brand-name">Forge<span>quote</span></div>
        </div>

        <nav className="primary-nav" aria-label="Main navigation">
          <div className="nav-label">Workspace</div>
          {nav.map((item) => (
            <button key={item.label} className={`nav-item ${activeNav === item.label ? "active" : ""}`} onClick={() => setActiveNav(item.label)}>
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {item.label === "RFQ Inbox" && rfq && <span className="nav-count">{open.length}</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="security-card">
            <div className="security-icon"><Icon name="shield" size={17} /></div>
            <div>
              <strong>Block Convey AI</strong>
              <span>Audit trail is active</span>
            </div>
            <span className="live-dot" />
          </div>
          <div className="profile">
            <div className="avatar">MK</div>
            <div><strong>Marcus Kim</strong><span>Sales operations</span></div>
            <Icon name="more" />
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="breadcrumb"><span>RFQ Inbox</span><Icon name="chevron" size={14} /><strong>{rfq ? rfq.rfq_id : composing ? "New RFQ" : "RFQ-1048"}</strong></div>
          <div className="top-actions">
            <div className="search-box" title={model ? `AI gateway model: ${model}` : "QuotePilot API not reachable"}><Icon name="search" size={16} /><span>Search catalog</span><kbd>⌘ K</kbd></div>
            <button className="icon-button" aria-label="Activity" onClick={() => rfq && setActiveTab("Activity")}><Icon name="activity" /></button>
            <button className="primary-button" onClick={reset}><Icon name="plus" size={16} />New RFQ</button>
          </div>
        </header>

        <div className="workspace">
          {!rfq && !composing ? (
            <Example assistant={<Assistant message={message} />} onNew={reset} />
          ) : (<>
          <section className="title-row">
            <div>
              <div className="eyebrow"><span className="status-pulse" />{busy ? busy.toUpperCase() : rfq ? rfq.status.replace(/_/g, " ").toUpperCase() : "WAITING FOR AN RFQ"}</div>
              <div className="page-title" role="heading" aria-level={1}>{rfq ? rfq.rfq_id : "New RFQ"} <span>{rfq ? rfq.buyer_id : buyer}</span></div>
              <div className="subtitle">{rfq ? `${fileName ? `Uploaded ${fileName}` : "Pasted text"} · ${new Date(rfq.created_at).toLocaleString()} · ${rfq.line_count} line items · ${rfq.parser_mode}` : "Paste an RFQ below or drop a PDF, spreadsheet, CSV or email."}</div>
            </div>
            <div className="title-actions">
              {rfq && <button className="secondary-button" onClick={copyEmail} disabled={!!busy || !open.length}><Icon name="download" size={16} />Copy buyer email</button>}
              {rfq && <button className="primary-button" onClick={allApproved ? draft : approveReady} disabled={!!busy || (!allApproved && !ready.length)}>{allApproved ? "Draft quote" : `Approve ${ready.length} ready line${ready.length === 1 ? "" : "s"}`}<Icon name="arrow" size={16} /></button>}
            </div>
          </section>

          {error && <div className="api-error" role="alert"><strong>Error</strong> {error}</div>}

          {rfq && (
            <section className="pipeline" aria-label="RFQ processing progress">
              {steps.map(([t, sub, icon, done], index) => (
                <div className={`pipeline-step ${done && (index === 4 || !steps[index + 1]?.[3]) ? "current" : ""}`} key={t}>
                  <div className="step-icon"><Icon name={icon} size={16} /></div>
                  <div><strong>{t}</strong><span>{sub}</span></div>
                  {index < 4 && <div className="connector" />}
                </div>
              ))}
            </section>
          )}

          <div className="content-grid">
            <section className="work-panel">
              <div className="tabs">
                {["Line items", "Source document", "Activity"].map((tab) => (
                  <button className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)} key={tab}>
                    {tab}{tab === "Line items" && rfq && <span>{rfq.line_count}</span>}
                  </button>
                ))}
              </div>

              {!rfq ? (
                <div className="intake">
                  <label htmlFor="buyer">Buyer</label>
                  <input id="buyer" value={buyer} onChange={(e) => setBuyer(e.target.value)} />
                  <label htmlFor="raw-rfq">RFQ text</label>
                  <textarea id="raw-rfq" rows={8} value={sourceText} onChange={(e) => setSourceText(e.target.value)} />
                  <div className="intake-actions">
                    <span>{busy || "Runs live extraction through the Nicrron gateway, then catalog, pricing and compliance."}</span>
                    <button className="primary-button" onClick={() => process()} disabled={!!busy || sourceText.trim().length < 4}><Icon name="spark" size={15} />Process RFQ</button>
                  </div>
                </div>
              ) : activeTab === "Line items" ? (
                <>
                  <div className="table-head table-grid">
                    <span>Original request</span><span>Normalized match & specification</span><span>Quantity</span><span>Quote</span><span>Status</span>
                  </div>
                  <div className="item-list">
                    {lines.map((l, i) => {
                      const st = STATUS_LABEL[l.status] || { text: l.status, cls: "review" };
                      return (
                        <button className={`item-row table-grid ${current?.id === l.id ? "selected" : ""}`} key={l.id} onClick={() => setSelectedLine(l.id)}>
                          <div className="original-cell"><span className="line-number">{String(i + 1).padStart(2, "0")}</span><div><strong>{l.raw_text}</strong><span>{l.id}</span></div></div>
                          <div className="match-cell"><strong>{title(l)}</strong><span>{spec(l) || "—"}</span>{l.match ? <em><Icon name="check" size={11} />{l.match.sku}</em> : <span className="no-match">{l.blockers.length ? `Missing: ${l.blockers.join(", ").replace(/_in/g, "")}` : "No catalog match"}</span>}</div>
                          <div className="quantity-cell"><strong>{l.quantity ?? "?"} {l.unit || ""}</strong><span>Requested</span></div>
                          <div className="quote-cell"><strong>{money(l.pricing?.line_total_usd)}</strong><span>{l.pricing ? `${money(l.pricing.unit_price_usd)} / unit` : "Not priced"}</span></div>
                          <div className="confidence-cell"><span className={`item-status ${st.cls}`}>{st.text}</span></div>
                        </button>
                      );
                    })}
                  </div>
                  <div className="table-footer">
                    <span><Icon name="spark" size={15} />Extracted via Nicrron · {rfq.gateway?.model || "unknown model"} · {rfq.gateway?.validation || ""}</span>
                    <span>Synthetic demo prices</span>
                  </div>
                </>
              ) : activeTab === "Source document" ? (
                <div className="document-preview">
                  <div className="file-card"><Icon name="document" size={30} /><div><strong>{fileName || "Pasted RFQ text"}</strong><span>{rfq.parser_mode}</span></div></div>
                  {!fileName && <pre className="source-text">{sourceText}</pre>}
                </div>
              ) : (
                <div className="activity-list">
                  {[...rfq.events].reverse().map((ev, i) => <div className="activity-row" key={i}><div className="activity-dot"><Icon name="check" size={13} /></div><div><strong>{ev.type}</strong><span>{ev.detail}</span></div><time>{new Date(ev.at).toLocaleTimeString()}</time></div>)}
                </div>
              )}
            </section>

            <aside className="right-panel">
              <Assistant message={message} />

              <div className="summary-card">
                <div className="card-heading"><div><span>{quote ? `Quote ${quote.id}` : "Draft quote"}</span><strong>{money(quote ? quote.grand_total_usd : subtotal)}</strong></div><span className="draft-badge">{quote ? quote.status.replace(/_/g, " ").toUpperCase() : "DRAFT"}</span></div>
                <div className="summary-lines">
                  <div><span>Priced lines</span><strong>{priced.length} of {lines.length}</strong></div>
                  <div><span>Waiting on buyer</span><strong>{open.length}</strong></div>
                  <div><span>Approved</span><strong>{lines.filter((l) => l.status === "approved").length}</strong></div>
                  <div><span>Ready to send</span><strong>{quote ? (quote.ready_to_send ? "Yes" : "No (demo data)") : "—"}</strong></div>
                </div>
                {quote?.warnings.map((w) => <small className="quote-warning" key={w}>{w}</small>)}
                <button className="primary-button full" onClick={allApproved ? draft : approveReady} disabled={!rfq || !!busy || (!allApproved && !ready.length)}>
                  {allApproved ? (quote ? "Redraft quote" : "Draft quote") : "Approve ready lines"}<Icon name="arrow" size={16} />
                </button>
                {quote && <button className="text-button" onClick={() => navigator.clipboard.writeText(JSON.stringify(quote, null, 2)).catch(() => undefined)}>Copy quote JSON</button>}
              </div>

              {current && (
                <div className="review-card">
                  <div className="card-title"><div><Icon name="spark" size={17} />{current.clarifications.length || current.blockers.length ? "Needs your attention" : "Line detail"}</div><span>{open.length}</span></div>
                  <div className="attention-content">
                    <div className="attention-head"><span className="amber-icon"><Icon name="clock" size={15} /></span><div><strong>{current.raw_text}</strong><span>{current.id} · {(STATUS_LABEL[current.status] || { text: current.status }).text}</span></div></div>
                    {current.pricing && <p>{current.pricing.explanation}{current.pricing.below_benchmark_pct != null ? ` ${current.pricing.below_benchmark_pct}% below benchmark.` : ""}</p>}
                    {current.compliance.issues.length > 0 && <p className="issue">{current.compliance.issues.join(" · ")}</p>}
                    {current.clarifications.map((c) => (
                      <div className="question-box" key={c.field}>
                        <span>{FIELD_LABEL[c.field] || c.field}</span>
                        <p>{c.question}</p>
                        {CLARIFY_FIELDS.has(c.field) && (
                          <input aria-label={FIELD_LABEL[c.field] || c.field} type={NUMERIC.has(c.field) ? "number" : "text"} step="any"
                            value={answers[`${current.id}.${c.field}`] || ""} placeholder="Buyer's answer"
                            onChange={(e) => setAnswers((a) => ({ ...a, [`${current.id}.${c.field}`]: e.target.value }))} />
                        )}
                      </div>
                    ))}
                    {current.clarifications.some((c) => CLARIFY_FIELDS.has(c.field)) && (
                      <div className="attention-actions"><button className="dark-button" onClick={() => submitAnswers(current)} disabled={!!busy}>Apply answers</button></div>
                    )}
                  </div>
                </div>
              )}

              <div className="audit-card">
                <div className="audit-icon"><Icon name="shield" size={17} /></div>
                <div><strong>Fully auditable</strong><span>{rfq ? `${rfq.events.length} events logged for this RFQ` : "Every step is logged"}</span></div>
                <button aria-label="View activity" onClick={() => setActiveTab("Activity")}><Icon name="chevron" size={16} /></button>
              </div>
            </aside>
          </div>
          </>)}

          <section className="upload-strip" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) process(f); }}>
            <input ref={fileInput} type="file" onChange={(e) => { const f = e.target.files?.[0]; if (f) process(f); e.target.value = ""; }} />
            <div className="upload-icon"><Icon name="upload" size={17} /></div>
            <div><strong>{rfq ? "Have another RFQ?" : composing ? "Or upload a file" : "Have another RFQ?"}</strong><span>Drop any file here: PDF, photo or screenshot, spreadsheet, Word, CSV or email</span></div>
            <button className="secondary-button" onClick={() => fileInput.current?.click()} disabled={!!busy}>Browse files</button>
          </section>
        </div>
      </main>
    </div>
  );
}

export default App;
