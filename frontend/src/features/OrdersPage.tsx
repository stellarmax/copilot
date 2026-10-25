import { useState } from "react";
import type { FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, SlidersHorizontal } from "lucide-react";
import { ClaimBadge } from "../components/ClaimBadge";
import { ErrorState, LoadingState } from "../components/Feedback";
import { getOrders } from "../lib/api";

interface OrdersPageProps {
  onTrace: (claimId: string) => void;
}

interface Filters {
  order_id: string;
  customer: string;
  status: string;
  stage: string;
}

const emptyFilters: Filters = { order_id: "", customer: "", status: "", stage: "" };

export function OrdersPage({ onTrace }: OrdersPageProps) {
  const [draft, setDraft] = useState(emptyFilters);
  const [filters, setFilters] = useState(emptyFilters);
  const [page, setPage] = useState(0);
  const query = useQuery({
    queryKey: ["orders", filters, page],
    queryFn: () => getOrders({ ...filters, limit: 12, offset: page * 12 }),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFilters(draft);
    setPage(0);
  }

  const data = query.data?.data;
  const pagination = data?.pagination;

  return (
    <div className="page-stack">
      <section className="page-intro">
        <div><span className="eyebrow">LIVE FROM THE ORDER REGISTER</span><p>Search and compare the current order book. Filters combine to narrow the result set.</p></div>
        {query.data?.claim_refs[0] && <ClaimBadge claimId={query.data.claim_refs[0].claim_id} onClick={onTrace} />}
      </section>
      <section className="panel filter-panel">
        <div className="filter-title"><SlidersHorizontal size={16} /><strong>Find orders</strong><span>AND filters</span></div>
        <form className="filter-form" onSubmit={submit}>
          <label>Order ID<input value={draft.order_id} onChange={(event) => setDraft({ ...draft, order_id: event.target.value })} placeholder="ORD-101" /></label>
          <label>Customer<input value={draft.customer} onChange={(event) => setDraft({ ...draft, customer: event.target.value })} placeholder="Customer name" /></label>
          <label>Status<select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="">All statuses</option><option value="IN_PROGRESS">In progress</option><option value="COMPLETE">Complete</option></select></label>
          <label>Stage<select value={draft.stage} onChange={(event) => setDraft({ ...draft, stage: event.target.value })}><option value="">All stages</option><option>KNITTING</option><option>ASSEMBLY</option><option>WASHING</option><option>PACKING</option><option>COMPLETE</option></select></label>
          <button className="button button-primary" type="submit"><Search size={16} /> Search</button>
        </form>
      </section>

      <section className="panel table-panel">
        <div className="panel-heading table-heading">
          <div><span className="eyebrow">MATCHING ORDERS</span><h2>{data?.match_count ?? "—"} <small>records</small></h2></div>
          <div className="table-total"><span>Total matched</span><strong>{data?.matched_total_pieces?.toLocaleString() ?? "—"} <small>pieces</small></strong></div>
        </div>
        {query.isLoading && <LoadingState label="Loading orders" />}
        {query.error && <ErrorState message={query.error.message} />}
        {data && data.orders.length === 0 && <div className="empty-row">No orders match these filters.</div>}
        {data && data.orders.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>ORDER</th><th>CUSTOMER</th><th>PRODUCT</th><th>QUANTITY</th><th>STAGE</th><th>DUE DATE</th><th>STATUS</th></tr></thead>
              <tbody>{data.orders.map((order) => (
                <tr key={order.order_id}>
                  <td><strong className="mono">{order.order_id}</strong></td>
                  <td>{order.customer}</td>
                  <td>{order.product}<small className="cell-sub">{order.category}</small></td>
                  <td className="mono">{order.pieces.toLocaleString()}</td>
                  <td><span className="stage-label">{order.current_stage}</span></td>
                  <td className="mono">{order.due_date}</td>
                  <td><span className={`status-pill ${order.status === "COMPLETE" ? "status-complete" : "status-progress"}`}>{order.status.replaceAll("_", " ")}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        {pagination && pagination.limit !== null && (
          <div className="pagination-row">
            <span>Showing {pagination.offset + 1}–{pagination.offset + pagination.returned_count} of {data?.match_count}</span>
            <div><button className="button button-secondary button-small" onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0}>Previous</button><button className="button button-secondary button-small" onClick={() => setPage(page + 1)} disabled={!pagination.has_more}>Next</button></div>
          </div>
        )}
      </section>
      <p className="subtle-footnote">Order quantities describe full orders. Production records are factory-wide and are not allocated to individual orders.</p>
    </div>
  );
}