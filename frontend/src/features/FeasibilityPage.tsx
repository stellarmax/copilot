import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowRight, BadgeCheck, CircleAlert, Factory, Truck } from "lucide-react";
import { ClaimBadge } from "../components/ClaimBadge";
import { ErrorState } from "../components/Feedback";
import { estimateFeasibility } from "../lib/api";

interface FeasibilityPageProps {
  onTrace: (claimId: string) => void;
}

export function FeasibilityPage({ onTrace }: FeasibilityPageProps) {
  const [product, setProduct] = useState("Hoodie");
  const [category, setCategory] = useState("TOPS");
  const [pieces, setPieces] = useState("500");
  const [dueDate, setDueDate] = useState("2026-04-30");
  const [outsourcing, setOutsourcing] = useState(true);
  const estimate = useMutation({ mutationFn: estimateFeasibility });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    estimate.mutate({ product, category, pieces: Number(pieces), requested_due_date: dueDate, allow_outsourcing: outsourcing });
  }

  const response = estimate.data;
  const data = response?.data;
  const passed = data?.classification === "LIKELY_FEASIBLE" || data?.classification === "FEASIBLE_WITH_OUTSOURCING";

  return (
    <div className="page-stack">
      <section className="page-intro"><div><span className="eyebrow">CAPACITY SCENARIO</span><p>Estimate the likely production window using recent stage output and the current order book.</p></div></section>
      <div className="feasibility-layout">
        <section className="panel estimate-form-panel">
          <div className="panel-heading"><div><span className="eyebrow">PROPOSED ORDER</span><h2>Scenario inputs</h2></div><span className="input-index">01 / 02</span></div>
          <form className="scenario-form" onSubmit={submit}>
            <label>Product<input value={product} onChange={(event) => setProduct(event.target.value)} required /></label>
            <label>Category<select value={category} onChange={(event) => setCategory(event.target.value)}><option>TOPS</option><option>ACCESSORIES</option></select></label>
            <label>Quantity (pieces)<input type="number" min="1" step="1" value={pieces} onChange={(event) => setPieces(event.target.value)} required /></label>
            <label>Requested due date<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} required /></label>
            <label className="switch-row"><span><strong>Evaluate outsourcing</strong><small>Include eligible workshop scenarios</small></span><input type="checkbox" checked={outsourcing} onChange={(event) => setOutsourcing(event.target.checked)} /></label>
            <button className="button button-primary button-wide" type="submit" disabled={estimate.isPending}>
              {estimate.isPending ? "Calculating scenario" : "Estimate feasibility"}<ArrowRight size={16} />
            </button>
          </form>
          <p className="form-caveat">Decision support only. This is not a production schedule or delivery commitment.</p>
        </section>

        <section className="estimate-result-column">
          {estimate.error && <ErrorState message={estimate.error.message} />}
          {!data && !estimate.isPending && !estimate.error && (
            <div className="estimate-empty"><div className="empty-symbol"><Factory size={21} /></div><span className="eyebrow">SCENARIO OUTPUT</span><h2>Build a planning view.</h2><p>Enter the proposed order details to compare internal capacity with eligible workshop options.</p><div className="empty-rule" /></div>
          )}
          {estimate.isPending && <div className="estimate-empty"><span className="loading-bars"><i /><i /><i /></span><span className="eyebrow">RUNNING DETERMINISTIC MODEL</span><h2>Checking stage capacity…</h2><p>Reading recent factory output, current orders and workshop constraints.</p></div>}
          {data && (
            <>
              <section className={`result-hero ${passed ? "result-good" : "result-caution"}`}>
                <div className="result-hero-top"><span className="eyebrow">FEASIBILITY CLASSIFICATION</span>{passed ? <BadgeCheck size={20} /> : <CircleAlert size={20} />}</div>
                <h2>{data.classification.replaceAll("_", " ")}</h2>
                <p>{data.confidence} confidence · {data.available_working_days} working days available</p>
                <div className="completion-window"><span>ESTIMATED COMPLETION</span><strong>{data.estimated_completion_range.earliest ?? "—"}<i>→</i>{data.estimated_completion_range.latest ?? "—"}</strong><small>Requested by {data.requested_due_date}</small></div>
                {response?.claim_refs[0] && <ClaimBadge claimId={response.claim_refs[0].claim_id} onClick={onTrace} />}
              </section>
              <div className="scenario-grid">
                <article className="scenario-tile"><div><Factory size={17} /><span>INTERNAL SCENARIO</span></div><strong>{String(data.internal_scenario.classification ?? "—").replaceAll("_", " ")}</strong><small>Bottleneck: {data.bottleneck_stage ?? "Not identified"}</small></article>
                <article className="scenario-tile"><div><Truck size={17} /><span>WORKSHOP OPTIONS</span></div><strong>{data.workshop_scenarios.length}</strong><small>Eligible scenarios assessed</small></article>
              </div>
              {data.assumptions.length > 0 && <section className="assumption-panel"><span className="eyebrow">MODEL ASSUMPTIONS</span>{data.assumptions.map((item) => <p key={item}>{item}</p>)}</section>}
              {data.limitations.length > 0 && <section className="assumption-panel limitation-panel"><span className="eyebrow">LIMITATIONS</span>{data.limitations.map((item) => <p key={item}>{item}</p>)}</section>}
            </>
          )}
        </section>
      </div>
    </div>
  );
}