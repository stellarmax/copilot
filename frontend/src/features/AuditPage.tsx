import { useQuery } from "@tanstack/react-query";
import { Check, Clock3, FileClock, X } from "lucide-react";
import { ErrorState, LoadingState } from "../components/Feedback";
import { getActionAudit } from "../lib/api";

const statusIcons: Record<string, typeof Check> = {
  PREPARED: Clock3,
  CONFIRMED: Check,
  CANCELLED: X,
};

export function AuditPage() {
  const query = useQuery({ queryKey: ["action-audit"], queryFn: getActionAudit });
  return (
    <div className="page-stack">
      <section className="page-intro"><div><span className="eyebrow">LOCAL SQLITE LEDGER</span><p>Prepared actions, confirmations and cancellations recorded by this demo instance.</p></div><span className="local-only-tag"><FileClock size={15} /> LOCAL RECORDS</span></section>
      <section className="panel table-panel">
        <div className="panel-heading table-heading"><div><span className="eyebrow">ACTION HISTORY</span><h2>{query.data?.length ?? "—"} <small>entries</small></h2></div></div>
        {query.isLoading && <LoadingState label="Loading action log" />}
        {query.error && <ErrorState message={query.error.message} />}
        {query.data?.length === 0 && <div className="empty-row">No actions have been prepared in this instance.</div>}
        {query.data && query.data.length > 0 && (
          <div className="table-scroll"><table className="data-table audit-table">
            <thead><tr><th>STATUS</th><th>ACTION</th><th>TARGET</th><th>PREPARED</th><th>CLAIM LINKS</th></tr></thead>
            <tbody>{[...query.data].reverse().map((entry) => {
              const Icon = statusIcons[entry.status] ?? Clock3;
              return <tr key={entry.confirmation_token}><td><span className={`status-pill status-${entry.status.toLowerCase()}`}><Icon size={12} />{entry.status}</span></td><td>{entry.action_type.replaceAll("_", " ")}</td><td className="mono">{entry.target}</td><td>{new Date(entry.prepared_at).toLocaleString()}</td><td>{entry.claim_ids.length ? `${entry.claim_ids.length} linked` : "—"}</td></tr>;
            })}</tbody>
          </table></div>
        )}
      </section>
      <div className="notice-strip"><span>!</span><p>This ledger records local effects only. It does not send messages or schedule reminders/watch jobs. This endpoint is unauthenticated; keep this demo on a trusted machine or network.</p></div>
    </div>
  );
}