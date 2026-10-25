import { useState } from "react";
import type { FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarRange, Download, RotateCcw } from "lucide-react";
import { ClaimBadge } from "../components/ClaimBadge";
import { ErrorState, LoadingState } from "../components/Feedback";
import { getProduction } from "../lib/api";

interface ProductionPageProps {
  onTrace: (claimId: string) => void;
}

export function ProductionPage({ onTrace }: ProductionPageProps) {
  const [draftStart, setDraftStart] = useState("2026-03-23");
  const [draftEnd, setDraftEnd] = useState("2026-03-29");
  const [draftStage, setDraftStage] = useState("");
  const [filters, setFilters] = useState({ start: draftStart, end: draftEnd, stage: "" });
  const query = useQuery({ queryKey: ["production", filters], queryFn: () => getProduction(filters) });
  const data = query.data?.data;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = { start: draftStart, end: draftEnd, stage: draftStage };
    // Same window again: the query key does not change, so re-read explicitly.
    if (next.start === filters.start && next.end === filters.end && next.stage === filters.stage) {
      void query.refetch();
    } else {
      setFilters(next);
    }
  }

  return (
    <div className="page-stack">
      <section className="page-intro">
        <div><span className="eyebrow">FACTORY-WIDE DAILY LOG</span><p>Stage totals are separate process counts. They are not summed into unique finished pieces.</p></div>
        {query.data?.claim_refs[0] && <ClaimBadge claimId={query.data.claim_refs[0].claim_id} onClick={onTrace} />}
      </section>
      <section className="panel filter-panel">
        <div className="filter-title"><CalendarRange size={17} /><strong>Reporting window</strong><span>Inclusive dates · Mon–Sat operating days</span></div>
        <form className="filter-form production-filter" onSubmit={submit}>
          <label>Start date<input type="date" value={draftStart} onChange={(event) => setDraftStart(event.target.value)} required /></label>
          <label>End date<input type="date" value={draftEnd} onChange={(event) => setDraftEnd(event.target.value)} required /></label>
          <label>Stage<select value={draftStage} onChange={(event) => setDraftStage(event.target.value)}><option value="">All stages</option><option>KNITTING</option><option>ASSEMBLY</option><option>WASHING</option><option>PACKING</option></select></label>
          <button className="button button-primary" type="submit"><RotateCcw size={15} className={query.isFetching ? "spin" : ""} /> Run report</button>
        </form>
      </section>

      <div className="production-summary-grid">
        {(data?.stage_summaries ?? []).map((stage, index) => (
          <article className={`production-summary summary-${index % 4}`} key={stage.stage}>
            <div className="summary-top"><span>{stage.stage}</span><span className={`coverage-dot coverage-${stage.coverage_status.toLowerCase()}`} /></div>
            <strong>{stage.total_pieces?.toLocaleString() ?? "—"}</strong>
            <span className="summary-label">observed pieces</span>
            <div className="summary-divider" />
            <div className="summary-average"><span>Per operating day</span><b>{stage.average_per_operating_day?.toLocaleString() ?? "—"}</b></div>
          </article>
        ))}
      </div>

      <section className="panel table-panel">
        <div className="panel-heading table-heading">
          <div><span className="eyebrow">DAILY RECORDS</span><h2>Output log</h2></div>
          {data && <span className={`coverage-chip ${data.coverage_status === "COMPLETE" ? "complete" : ""}`}>{data.coverage_status} COVERAGE</span>}
        </div>
        {query.isFetching && <LoadingState label="Loading production log" />}
        {query.error && <ErrorState message={query.error.message} />}
        {data && data.missing_keys.length > 0 && <div className="coverage-warning">{data.missing_keys.length} date-stage records are missing. A missing record is not treated as zero output.</div>}
        {data && data.daily_output.length > 0 ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>DATE</th><th>STAGE</th><th>OUTPUT</th><th>DAY TYPE</th></tr></thead>
              <tbody>{data.daily_output.map((row) => <tr key={`${row.date}-${row.stage}`}><td className="mono">{row.date}</td><td><span className="stage-label">{row.stage}</span></td><td className="mono">{row.pieces_completed.toLocaleString()} pcs</td><td>{row.is_closed_day ? "Closed day" : "Operating day"}</td></tr>)}</tbody>
            </table>
          </div>
        ) : data && <div className="empty-row">No production rows in this date range.</div>}
        {data && <div className="pagination-row"><span>{data.daily_output.length} visible rows · {data.missing_keys.length} missing keys</span><button className="button button-secondary button-small" onClick={() => window.print()}><Download size={14} /> Print report</button></div>}
      </section>
    </div>
  );
}