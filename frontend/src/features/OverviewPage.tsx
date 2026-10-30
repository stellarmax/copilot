import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowDownRight, ArrowRight, ArrowUpRight, BellRing, CalendarDays, CircleHelp, RefreshCw, Sparkles } from "lucide-react";
import { ClaimBadge } from "../components/ClaimBadge";
import { ChatEntry } from "../components/ChatEntry";
import { ErrorState, InlineError, LoadingState } from "../components/Feedback";
import { generateBrief, getOrders, getProduction, getReminders, type BriefData, type BriefFinding } from "../lib/api";
import { DUE_LABELS, formatWhen } from "../lib/reminders";

interface OverviewPageProps {
  onTrace: (claimId: string) => void;
  onAsk: (message: string) => void;
}

const weekStart = "2026-03-23";
const weekEnd = "2026-03-29";

function severityIcon(severity: string) {
  if (severity === "CRITICAL") return <ArrowUpRight size={15} />;
  if (severity === "WARNING") return <ArrowDownRight size={15} />;
  return <CircleHelp size={15} />;
}

function FindingRow({ finding, onTrace }: { finding: BriefFinding; onTrace: (id: string) => void }) {
  return (
    <article className={`finding-row severity-${finding.severity.toLowerCase()}`}>
      <div className="finding-priority"><span>{severityIcon(finding.severity)}</span><b>{Math.round(finding.priority)}</b></div>
      <div className="finding-copy">
        <div className="finding-meta"><span className={`severity-label ${finding.severity.toLowerCase()}`}>{finding.severity}</span><span>{finding.category.replaceAll("_", " ")}</span></div>
        <h3>{finding.summary}</h3>
        <p>{finding.recommended_next_step}</p>
      </div>
      <ClaimBadge claimId={finding.claim_id} onClick={onTrace} />
    </article>
  );
}

function BriefResults({ brief, onTrace }: { brief: BriefData; onTrace: (id: string) => void }) {
  const [showObservations, setShowObservations] = useState(false);
  return (
    <>
      <div className="finding-list">
        {brief.findings.length === 0 ? <div className="empty-row">No prioritized findings in this run.</div> : brief.findings.map((finding) => <FindingRow key={finding.finding_id} finding={finding} onTrace={onTrace} />)}
      </div>
      {(brief.not_shown_findings?.length ?? 0) > 0 && (
        <div className="not-shown-note">
          <strong>{brief.not_shown_findings!.length} more above the threshold, not in the top {brief.findings.length}:</strong>
          {brief.not_shown_findings!.map((item) => <span key={item.summary}>{item.summary}</span>)}
        </div>
      )}
      {brief.observation_findings.length > 0 && (
        <div className="observation-block">
          <button className="text-button" onClick={() => setShowObservations(!showObservations)}>
            {showObservations ? "Hide" : "Show"} {brief.observation_findings.length} observations <ArrowRight size={14} />
          </button>
          {showObservations && <div className="observation-list">{brief.observation_findings.map((item) => <FindingRow key={item.finding_id} finding={item} onTrace={onTrace} />)}</div>}
        </div>
      )}
    </>
  );
}

function DueReminders() {
  const reminders = useQuery({ queryKey: ["reminders", false], queryFn: () => getReminders(false), refetchInterval: 60_000 });
  const due = (reminders.data ?? []).filter((item) => item.due_state === "OVERDUE" || item.due_state === "DUE_SOON");
  if (!reminders.data || due.length === 0) return null;
  return (
    <section className="panel due-reminders" aria-label="Due reminders">
      <div className="panel-heading">
        <div><span className="eyebrow">FOLLOW-UPS</span><h2><BellRing size={17} /> {due.length} reminder{due.length > 1 ? "s" : ""} due</h2></div>
        <Link className="text-link" to="/reminders">Open reminders <ArrowRight size={15} /></Link>
      </div>
      <ul className="due-list">
        {due.slice(0, 5).map((item) => (
          <li key={item.reminder_id}>
            <span className={`due-chip due-${item.due_state.toLowerCase()}`}>{DUE_LABELS[item.due_state]}</span>
            <span className="mono">{item.order_id}</span>
            <span className="due-note">{item.note}</span>
            <span className="mono due-when">{formatWhen(item.remind_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function OverviewPage({ onTrace, onAsk }: OverviewPageProps) {
  const orders = useQuery({ queryKey: ["orders", "overview"], queryFn: () => getOrders({ limit: 6 }) });
  const production = useQuery({
    queryKey: ["production", weekStart, weekEnd],
    queryFn: () => getProduction({ start: weekStart, end: weekEnd }),
  });
  const [brief, setBrief] = useState<BriefData | null>(null);
  const runBrief = useMutation({ mutationFn: generateBrief, onSuccess: (response) => setBrief(response.data) });
  const orderData = orders.data?.data;
  const stageSummaries = production.data?.data.stage_summaries ?? [];
  const maxOutput = Math.max(1, ...stageSummaries.map((stage) => stage.total_pieces ?? 0));

  return (
    <div className="overview-page page-stack">
      <section className="brief-banner">
        <div className="brief-banner-copy">
          <div className="eyebrow light">TUESDAY, APRIL 01 <span>·</span> DAILY CHECK-IN</div>
          <h2>Know where to<br /><em>look first.</em></h2>
          <p>Prioritized operational findings, backed by traceable data and deterministic rules.</p>
        </div>
        <div className="brief-banner-side">
          <div className="brief-orbit" aria-hidden="true"><span /><span /><span /><i /></div>
          <div className="brief-run-control">
            <span className="live-note"><i /> TRACK 1 DATASET</span>
            <button className="button button-lime" onClick={() => runBrief.mutate()} disabled={runBrief.isPending}>
              <Sparkles size={16} /> {runBrief.isPending ? "Running checks" : "Generate morning brief"}
            </button>
          </div>
        </div>
      </section>
      {runBrief.error && <ErrorState message={runBrief.error.message} />}
      <DueReminders />
      <ChatEntry onAsk={onAsk} />

      <section className="metric-grid" aria-label="Operations summary">
        <article className="metric-tile metric-ink">
          <div className="metric-top"><span>OPEN ORDER BOOK</span><BoxesMark /></div>
          {orders.isLoading ? <LoadingState label="Loading orders" /> : <strong>{orderData?.match_count ?? "—"}<small> orders</small></strong>}
          <div className="metric-foot"><span>{orderData?.matched_total_pieces?.toLocaleString() ?? "—"} pieces in scope</span><span className="metric-arrow"><ArrowUpRight size={16} /></span></div>
        </article>
        <article className="metric-tile metric-paper">
          <div className="metric-top"><span>PRODUCTION COVERAGE</span><CalendarDays size={17} /></div>
          {production.isLoading ? <LoadingState label="Loading output" /> : <strong>{production.data?.data.coverage_status ?? "—"}<small> coverage</small></strong>}
          <div className="metric-foot"><span>{weekStart} — {weekEnd}</span><span className="metric-arrow"><ArrowUpRight size={16} /></span></div>
        </article>
        <article className="metric-tile metric-citrus">
          <div className="metric-top"><span>BRIEF STATUS</span><Sparkles size={17} /></div>
          <strong>{brief ? brief.overview.published_count : "—"}<small> priorities</small></strong>
          <div className="metric-foot"><span>{brief ? `${brief.overview.observation_count} in observation` : "Run checks to review today"}</span><span className="metric-arrow"><ArrowUpRight size={16} /></span></div>
        </article>
      </section>

      <div className="overview-grid">
        <section className="panel brief-panel">
          <div className="panel-heading">
            <div><span className="eyebrow">PRIORITY QUEUE</span><h2>Morning brief</h2></div>
            {brief && <button className="icon-button" onClick={() => runBrief.mutate()} aria-label="Refresh morning brief" title="Refresh"><RefreshCw size={16} /></button>}
          </div>
          {runBrief.isPending && <LoadingState label="Checking orders and production signals" />}
          {!brief && !runBrief.isPending && (
            <div className="brief-empty">
              <div className="empty-symbol"><Sparkles size={21} /></div>
              <div><strong>Brief not generated</strong><p>Run the deterministic checks to see the highest-priority findings.</p></div>
            </div>
          )}
          {brief && <BriefResults brief={brief} onTrace={onTrace} />}
        </section>

        <section className="panel stage-panel">
          <div className="panel-heading">
            <div><span className="eyebrow">WEEKLY OUTPUT</span><h2>Stage throughput</h2></div>
            <span className={`coverage-chip ${production.data?.data.coverage_status === "COMPLETE" ? "complete" : ""}`}>{production.data?.data.coverage_status ?? "—"}</span>
          </div>
          {production.isLoading && <LoadingState label="Loading production data" />}
          {production.error && <ErrorState message={production.error.message} />}
          <div className="stage-bars">
            {stageSummaries.map((stage) => {
              const amount = stage.total_pieces ?? 0;
              return (
                <div className="stage-bar-row" key={stage.stage}>
                  <div className="stage-bar-meta"><span>{stage.stage}</span><strong>{amount.toLocaleString()} <small>pcs</small></strong></div>
                  <div className="bar-track"><span style={{ width: `${Math.max(2, (amount / maxOutput) * 100)}%` }} /></div>
                  <div className="stage-average">{stage.average_per_operating_day?.toLocaleString() ?? "—"}<span> / operating day</span></div>
                </div>
              );
            })}
          </div>
          {production.data && <div className="panel-bottom-note">Totals are stage-level counts, not unique finished garments.</div>}
          {production.error && <button className="text-button" onClick={() => production.refetch()}>Retry <ArrowRight size={14} /></button>}
        </section>
      </div>

      <section className="panel orders-panel">
        <div className="panel-heading">
          <div><span className="eyebrow">LATEST RECORDS</span><h2>Order pulse</h2></div>
          <a className="text-link" href="/orders">Open order book <ArrowRight size={15} /></a>
        </div>
        {orders.error && <InlineError error={orders.error} />}
        {orders.isLoading ? <LoadingState label="Loading order records" /> : (
          <div className="compact-table-wrap">
            <table className="data-table compact-table">
              <thead><tr><th>ORDER</th><th>CUSTOMER</th><th>PRODUCT / STAGE</th><th>DUE DATE</th><th>STATE</th></tr></thead>
              <tbody>{(orderData?.orders ?? []).slice(0, 5).map((order) => (
                <tr key={order.order_id}>
                  <td><strong className="mono">{order.order_id}</strong></td>
                  <td>{order.customer}</td>
                  <td>{order.product}<small className="cell-sub">{order.current_stage}</small></td>
                  <td className="mono">{order.due_date}</td>
                  <td><span className={`status-pill ${order.status === "COMPLETE" ? "status-complete" : "status-progress"}`}>{order.status.replaceAll("_", " ")}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
      {orders.data?.claim_refs[0] && <div className="overview-evidence"><ClaimBadge claimId={orders.data.claim_refs[0].claim_id} onClick={onTrace} /></div>}
    </div>
  );
}

function BoxesMark() {
  return <span className="metric-glyph" aria-hidden="true"><span /><span /><span /></span>;
}