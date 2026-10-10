import { useEffect, useRef } from "react";
import Icon, { type IconName } from "./Icon";
import { money, type Line, type RFQ } from "./api";

// "AI reasoning" panel under the pipeline: what the agent checked for this RFQ, step by step.
// Every entry is built from the API response itself (gateway, lines, match, compliance, pricing);
// nothing here is invented in the browser.

const STEPS: [string, IconName][] = [
  ["Parse & normalize", "check"],
  ["Catalog matching", "cube"],
  ["Compliance", "shield"],
  ["Price benchmark", "activity"],
  ["Quote ready", "spark"],
];

const n = (i: number) => `Line ${i + 1}`;
const secs = (ms?: number) => `${((ms || 0) / 1000).toFixed(1)}s`;
const pretty = (v?: string | null) => (v || "").replace(/_/g, " ");

function specOf(l: Line) {
  const size = l.width_in && l.length_in ? `${l.width_in} × ${l.length_in} in` : null;
  return [pretty(l.material) || "material ?", pretty(l.form) || "form ?", l.grade || "grade ?",
    l.thickness_in != null ? `${l.thickness_in} in` : "thickness ?", size || "size ?", `qty ${l.quantity ?? "?"}`].join(" · ");
}

function entries(r: RFQ): string[][] {
  const g = r.gateway || {};
  const parse = [
    g.vision_model
      ? (g.extract_latency_ms ? `Read the file with ${g.vision_model} (${secs(g.vision_latency_ms)}), then extracted lines (${secs(g.extract_latency_ms)}).`
          : `Read the file and extracted the lines in one call to ${g.vision_model} (${secs(g.vision_latency_ms || g.latency_ms)}).`)
      : `Extracted ${r.line_count} lines with ${g.model || r.parser_mode} in ${secs(g.latency_ms)}.`,
    g.validation ? `Every extracted value was checked against the source text (${g.validation}).` : "",
    ...r.lines.map((l, i) => `${n(i)}: “${l.raw_text}” → ${specOf(l)}`),
  ].filter(Boolean);

  const match = r.lines.map((l, i) =>
    l.match ? `${n(i)}: matched ${l.match.sku} from ${l.match.supplier}. ${l.match.reason}`
      : (l.match_candidates?.length || 0) > 1 ? `${n(i)}: ${l.match_candidates!.length} compatible SKUs (${l.match_candidates!.join(", ")}); needs a choice.`
      : `${n(i)}: no compatible catalog SKU yet${l.blockers.length ? ` (${l.blockers.every((b) => /^[a-z_]+$/.test(b)) ? `missing ${l.blockers.join(", ").replace(/_in/g, "").replace(/_/g, " ")}` : l.blockers.join("; ")})` : ""}.`);

  const evaluated = r.lines.map((l, i) => [l, i] as const).filter(([l]) => l.compliance.status !== "not_evaluated");
  const comply = evaluated.length
    ? evaluated.map(([l, i]) => {
        const req = l.required_certificates?.length ? `buyer requires ${l.required_certificates.join(", ")}` : "no certificates requested";
        const have = l.compliance.available_certificates?.length ? `supplier lists ${l.compliance.available_certificates.join(", ")}` : "supplier lists no certificates";
        return l.compliance.status === "pass"
          ? `${n(i)}: passes (${req}; ${have}; standard ${l.compliance.supplier_standard || "n/a"}).`
          : `${n(i)}: blocked: ${l.compliance.issues.join("; ")} (${req}; ${have}).`;
      })
    : ["No line has a catalog match yet, so there is nothing to check for compliance."];

  const pricedLines = r.lines.map((l, i) => [l, i] as const).filter(([l]) => l.pricing);
  const price = pricedLines.length
    ? pricedLines.map(([l, i]) => {
        const p = l.pricing!;
        const vs = p.below_benchmark_pct == null ? "no benchmark to compare"
          : p.below_benchmark_pct >= 0 ? `${p.below_benchmark_pct}% below the benchmark` : `${Math.abs(p.below_benchmark_pct)}% above the benchmark`;
        return `${n(i)}: cost ${money(p.supplier_cost_usd)} × (1 + ${p.markup_pct}% markup) = ${money(p.unit_price_usd)}/unit vs benchmark ${money(p.benchmark_unit_usd)} (${p.benchmark_source}, ${p.benchmark_as_of}) → ${vs}. Line total ${money(p.line_total_usd)}.`;
      })
    : ["No line is priced yet: prices need a catalog match first."];

  const ready = r.lines.filter((l) => l.status === "ready_for_approval").length;
  const questions = r.lines.filter((l) => l.clarifications.length).length;
  const quote = [`${ready} of ${r.line_count} lines are ready for approval, ${questions} need an answer from the buyer, ${r.approved} approved.`,
    questions ? "Lines with questions stay off the quote until they are answered; nothing is guessed." : "Approve the ready lines to draft the quote."];

  return [parse, match, comply, price, quote];
}

export default function Reasoning({ rfq, stage, pending, elapsed, model }:
  { rfq: RFQ | null; stage: number; pending: { name: string } | null; elapsed: number; model: string }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight, behavior: "smooth" }); }, [stage, rfq, elapsed > 0]);

  const groups = rfq ? entries(rfq) : [];
  return (
    <section className="reasoning" aria-label="AI reasoning">
      <div className="reasoning-head">
        <div><Icon name="spark" size={15} /><strong>AI reasoning</strong></div>
        <span>{pending ? "Working…" : stage < 4 ? `Step ${stage + 1} of 5` : "Every step below comes from this RFQ's data"}</span>
      </div>
      <div className="reasoning-body" ref={box}>
        {pending ? (
          <div className="reasoning-group">
            <div className="reasoning-title"><span className="step-spinner small" />Parse & normalize</div>
            <p>Sent {pending.name} to the Nicrron AI gateway{model ? ` (${model})` : ""}.</p>
            <p>Waiting for the model to read the file and return each line · {elapsed.toFixed(0)}s</p>
          </div>
        ) : (
          groups.map((items, step) => step > stage || (step === stage && stage < 4) ? (
            step === stage ? (
              <div className="reasoning-group" key={step}>
                <div className="reasoning-title"><span className="step-spinner small" />{STEPS[step][0]}</div>
                <p className="muted">Working…</p>
              </div>
            ) : null
          ) : (
            <div className="reasoning-group" key={step}>
              <div className="reasoning-title"><span className="reasoning-check"><Icon name="check" size={11} /></span>{STEPS[step][0]}</div>
              {items.map((t, k) => <p key={k}>{t}</p>)}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
