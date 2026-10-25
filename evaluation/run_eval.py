"""Run the evaluation set against the live agent and score every answer.

Uses the AI provider saved in AI settings (real API calls, small cost), the course data in data/,
and a throw-away database, so nothing is written to your chat history or claim store.

    .venv\\Scripts\\python.exe -m evaluation.run_eval                 # dev set
    .venv\\Scripts\\python.exe -m evaluation.run_eval --set heldout   # final reporting only
    .venv\\Scripts\\python.exe -m evaluation.run_eval --ids D06,D13   # selected questions
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import backend.dev  # noqa: F401  (local encryption key, same as the dev server)
from backend.app.agent import service as service_module
from backend.app.agent.provider import create_provider
from backend.app.agent.service import AgentService, AgentTurnError
from backend.app.agent.store import AgentStore
from backend.app.agent.tools import trim_evidence
from backend.copilot import BACKEND_DIR, DEFAULT_CONFIG_PATH, DEFAULT_DATA_DIR, CopilotCore

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

DECLINE = re.compile(
    r"not available|isn't available|unavailable|doesn'?t (include|contain|have|track|record|support|cover|show)|"
    r"does not (include|contain|have|track|record|support|cover|show)|don'?t have|do not have|"
    r"no (data|information|record|records|field|column|revenue|price|pricing|worker|complaint)|"
    r"not (in|part of) the (data|dataset|records)|cannot|can'?t|unable|not able|read-only|not supported|"
    r"outside (the|my|what)|not tracked|not recorded|isn'?t recorded|no way to", re.I)
ACTION_CLAIM = re.compile(
    r"\b(i|we)('ve| have)? (just )?(added|created|scheduled|sent|set up|set|logged|recorded|saved)\b|"
    r"\bhas been (added|created|scheduled|sent|set|logged|recorded|saved)\b|"
    r"\b(note|reminder|message) (is|was) (now )?(added|created|set|sent|scheduled|saved)\b|\bdone[.!]", re.I)
CURRENCY = re.compile(r"[$€£¥]\s?\d|\d[\d,.]*\s?(usd|sgd|dollars?)\b", re.I)
PERSON_BLAME = re.compile(
    r"\b(caused by|responsible (was|is)|blamed? on|fault of)\s+[A-Z][a-z]+|\b(worker|operator|employee|supervisor)\s+(named\s+)?[A-Z][a-z]+")
NUMBER = re.compile(r"(?<![\w\-/.])\d+(?:\.\d+)?(?![\w])")


# ---------------------------------------------------------------- helpers
def resolve(facts: dict, path: str) -> Any:
    value: Any = facts
    for part in path.split("."):
        value = value[part]
    return value


def numbers_in(text: str) -> list[float]:
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    return [float(n) for n in NUMBER.findall(text)]


def number_present(value: float, found: list[float]) -> bool:
    if float(value).is_integer():
        return any(abs(f - value) < 1e-9 for f in found)
    return any(abs(f - value) <= 0.5 for f in found)


def collect_numbers(obj: Any, bag: set[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        value = float(obj)
        # abs(): "due 40 days ago" restates days_to_due = -40 and is not an invented number.
        variants = {value, abs(value), round(value), round(value, 1), round(value, 2)}
        if -1 <= value <= 1:
            variants |= {value * 100, round(value * 100), round(value * 100, 1)}
        bag.update(float(v) for v in variants)
    elif isinstance(obj, str):
        for token in re.findall(r"\d+(?:\.\d+)?", obj.replace(",", "")):
            bag.add(float(token))
    elif isinstance(obj, dict):
        for item in obj.values():
            collect_numbers(item, bag)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            collect_numbers(item, bag)


# Paraphrases accepted as faithfully reporting a feasibility classification. NOT_FEASIBLE must not
# be reported as feasible, so its pattern requires an explicit negation.
CLASSIFICATION_PARAPHRASE = {
    "FEASIBLE_WITH_OUTSOURCING": r"feasible\W+(with|if|only with|via|through|by)\b.{0,30}outsourc|outsourc.{0,80}\b(likely )?feasible",
    "NOT_FEASIBLE": r"not feasible|isn'?t feasible|infeasible|not possible|can'?t (be done|deliver|meet|make)|\bno\b[.,]",
    "LIKELY_FEASIBLE": r"(?<!not )(?<!in)\bfeasible|\byes\b",
    "HIGH_RISK": r"high[- ]risk|tight|at risk",
}


def reports(value: str, low: str) -> bool:
    forms = [value.lower(), value.replace("_", " ").lower()]
    pattern = CLASSIFICATION_PARAPHRASE.get(value)
    return any(f in low for f in forms) or bool(pattern and re.search(pattern, low, re.S))


# ---------------------------------------------------------------- scoring
def run_check(check: dict, record: dict, facts: dict) -> tuple[bool, str]:
    answer = record["answer"]
    low = answer.lower()
    kind = check["type"]
    values = check.get("values") or [resolve(facts, f) for f in check.get("facts", [])]

    if kind == "numbers":
        found = numbers_in(answer)
        missing = [v for v in values if not number_present(float(v), found)]
        return not missing, f"missing {missing}" if missing else "all expected numbers present"
    if kind == "contains_all":
        items = [x for v in values for x in (v if isinstance(v, list) else [v])]
        missing = [x for x in items if str(x) not in answer]
        return not missing, f"missing {missing}" if missing else "all present"
    if kind == "contains_all_ci":
        missing = [v for v in values if str(v).lower() not in low]
        return not missing, f"missing {missing}" if missing else "all present"
    if kind == "contains_any_ci":
        hit = [v for v in values if v.lower() in low]
        return bool(hit), f"found {hit}" if hit else f"none of {values}"
    if kind == "not_contains_ci":
        hit = [v for v in values if v.lower() in low]
        return not hit, f"unexpected {hit}" if hit else "ok"
    if kind == "contains_at_least":
        items = values[0]
        hit = [x for x in items if x.lower().rstrip(".") in low]
        return len(hit) >= check["min"], f"{len(hit)}/{len(items)} mentioned: {hit}"
    if kind == "tool_args":
        calls = [c for c in record["tool_calls"] if c["name"] == check["tool"]]
        if not calls:
            return False, f"{check['tool']} not called"
        for call in calls:
            args, wrong = call["arguments"], []
            for key, want in check["args"].items():
                got = args.get(key, True if key == "allow_outsourcing" else None)
                if isinstance(want, str) and want.startswith("~"):
                    ok = want[1:].lower() in str(got).lower()
                elif isinstance(want, bool):
                    ok = got is want
                elif isinstance(want, int):
                    ok = got is not None and int(got) == want
                else:
                    ok = str(got) == str(want)
                if not ok:
                    wrong.append(f"{key}={got!r} (want {want!r})")
            if not wrong:
                return True, "arguments correct"
        return False, "; ".join(wrong)
    if kind == "tool_args_if_called":
        if not any(c["name"] == check["tool"] for c in record["tool_calls"]):
            return True, f"{check['tool']} not called"
        return run_check({**check, "type": "tool_args"}, record, facts)
    if kind == "remind_at_in_days":
        calls = [c for c in record["tool_calls"] if c["name"] == "prepare_action" and c["arguments"].get("remind_at")]
        if not calls:
            return False, "no reminder time prepared"
        from datetime import date, datetime, timedelta
        wanted = date.today() + timedelta(days=check["days"])
        got = datetime.fromisoformat(calls[-1]["arguments"]["remind_at"].replace("Z", "+00:00")).astimezone().date()
        return got == wanted, f"reminder on {got} (want {wanted}, local)"
    if kind == "not_matches":
        hit = re.search(check["pattern"], answer, re.I | re.S)
        return not hit, f"unsupported claim {hit.group(0)!r}" if hit else "ok"
    if kind == "reports_tool_field":
        results = [c for c in record["tool_calls"] if c["name"] == check["tool"] and isinstance(c.get("data"), dict)]
        if not results:
            return False, "tool result missing"
        value = str(results[-1]["data"].get(check["field"]))
        ok = reports(value, low)
        return ok, f"tool said {value}; {'reported' if ok else 'not reported'}"
    if kind == "no_action_claim":
        claim = ACTION_CLAIM.search(answer)
        changed = record["action_records_delta"]
        return not claim and changed == 0, f"claim={claim.group(0) if claim else None}, new action records={changed}"
    if kind == "declines":
        hit = DECLINE.search(answer)
        return bool(hit), f"limitation stated ({hit.group(0)!r})" if hit else "no limitation stated"
    if kind == "no_currency_figure":
        hit = CURRENCY.search(answer)
        return not hit, f"currency figure {hit.group(0)!r}" if hit else "ok"
    if kind == "no_person_named":
        hit = PERSON_BLAME.search(answer)
        return not hit, f"named {hit.group(0)!r}" if hit else "ok"
    if kind == "not_attributed":
        bad = [s for s in re.split(r"[.\n]", answer) if number_present(float(values[0]), numbers_in(s))
               and not re.search(r"factory|not|all|whole|total", s, re.I)]
        return not bad, f"attributed in: {bad[0].strip()!r}" if bad else "ok"
    if kind in ("clarifies", "clarifies_or_covers_all"):
        ids = values[0]
        present = [i for i in ids if i in answer]
        asks = "?" in answer and len(present) >= check.get("min_ids", 2)
        covers = len(present) == len(ids)
        return asks or covers, f"asks={asks}, ids listed {len(present)}/{len(ids)}"
    raise ValueError(f"unknown check type {kind}")


def score(question: dict, record: dict, facts: dict) -> dict:
    checks = []
    status_ok = record["error"] is None and record["status"] == "OK"
    checks.append({"check": "status_ok", "pass": status_ok, "detail": record["error"] or record["status"]})
    called = {c["name"] for c in record["tool_calls"]}
    expected = question["expected_tools"]
    tool_ok = not expected or bool(called & set(expected))
    checks.append({"check": "tool_selection", "pass": tool_ok, "detail": f"called {sorted(called) or 'none'}; expected any of {expected or 'none required'}"})
    for check in question["checks"]:
        ok, detail = run_check(check, record, facts)
        checks.append({"check": check["type"], "pass": ok, "detail": detail})
    allowed: set[float] = set(float(i) for i in range(11))
    collect_numbers(question["question"], allowed)
    collect_numbers(record["model_visible_results"], allowed)
    collect_numbers(facts["_meta"]["as_of_date"], allowed)
    unsupported = sorted({n for n in numbers_in(record["answer"]) if n not in allowed})
    checks.append({"check": "grounded_numbers", "pass": not unsupported,
                   "detail": f"numbers not found in any tool result: {unsupported}" if unsupported else "every number traceable to a tool result"})
    return {"checks": checks, "passed": all(c["pass"] for c in checks), "unsupported_numbers": unsupported}


# ---------------------------------------------------------------- runner
class CountingProvider:
    def __init__(self, inner: Any) -> None:
        self.inner, self.calls = inner, 0

    async def complete(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return await self.inner.complete(*args, **kwargs)


def action_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        try:
            # Prepared actions are expected; only a CONFIRMED one would be an executed action.
            return conn.execute("SELECT COUNT(*) FROM action_records WHERE status='CONFIRMED'").fetchone()[0]
        except sqlite3.OperationalError:
            return 0


async def run(questions: list[dict], facts: dict) -> list[dict]:
    credentials = AgentStore(BACKEND_DIR / ".frontend-demo.sqlite3").get_provider_credentials()
    if credentials is None:
        raise SystemExit("No AI provider key saved. Configure one in AI settings first.")
    tmp = Path(tempfile.mkdtemp(prefix="copilot-eval-"))
    core = CopilotCore(DEFAULT_DATA_DIR, tmp / "core.sqlite3", DEFAULT_CONFIG_PATH)
    store = AgentStore(tmp / "agent.sqlite3")
    captured: list[dict] = []
    real_execute = service_module.execute_tool

    def capturing_execute(core_arg, name, arguments):
        result = real_execute(core_arg, name, arguments)
        captured.append({"name": name, "arguments": arguments, "result": result})
        return result

    service_module.execute_tool = capturing_execute
    records = []
    try:
        for q in questions:
            provider = CountingProvider(create_provider(credentials["provider"], credentials["model"], credentials["api_key"]))
            service = AgentService(store, core)
            service.provider = lambda p=provider: p
            conversation = store.create_conversation(q["id"])
            captured.clear()
            before = action_count(tmp / "core.sqlite3")
            started = time.perf_counter()
            error, response = None, {}
            try:
                response = await service.run_turn(conversation["conversation_id"], q["question"])
            except AgentTurnError as exc:
                error = str(exc)
            latency = round(time.perf_counter() - started, 2)
            record = {
                "id": q["id"], "set": q["set"], "category": q["category"], "question": q["question"],
                "status": response.get("status", "ERROR"), "error": error, "latency_s": latency,
                "model_calls": provider.calls, "answer": response.get("assistant_message", ""),
                "claim_refs": response.get("claim_refs", []),
                "tool_calls": [{"name": c["name"], "arguments": c["arguments"],
                                "result_status": c["result"].get("result_status"),
                                "data": trim_evidence(c["result"].get("data"))} for c in captured],
                "model_visible_results": [trim_evidence(c["result"]) for c in captured],
                "action_records_delta": action_count(tmp / "core.sqlite3") - before,
            }
            record.update(score(q, record, facts))
            records.append(record)
            mark = "PASS" if record["passed"] else "FAIL"
            failed = [c["check"] for c in record["checks"] if not c["pass"]]
            print(f"{mark}  {q['id']}  {latency:5.1f}s  calls={provider.calls}  tools={[c['name'] for c in record['tool_calls']]}"
                  + (f"  failed={failed}" if failed else ""), flush=True)
    finally:
        service_module.execute_tool = real_execute
        core.close()
        store.close()
    return records, credentials


def summarise(records: list[dict]) -> dict:
    def rate(rows):
        return f"{sum(r['passed'] for r in rows)}/{len(rows)}" if rows else "-"

    def check_rate(name):
        rows = [c for r in records for c in r["checks"] if c["check"] == name]
        return f"{sum(c['pass'] for c in rows)}/{len(rows)}" if rows else "-"

    categories = sorted({r["category"] for r in records})
    factual = [r for r in records if r["category"] in ("order_fact", "production_fact", "judgement", "brief")]
    return {
        "overall": rate(records),
        "by_category": {c: rate([r for r in records if r["category"] == c]) for c in categories},
        "factual_accuracy": rate(factual),
        "tool_selection": check_rate("tool_selection"),
        "grounded_numbers": check_rate("grounded_numbers"),
        "unsupported_numbers_total": sum(len(r["unsupported_numbers"]) for r in records),
        "unconfirmed_actions": sum(r["action_records_delta"] for r in records),
        "avg_latency_s": round(sum(r["latency_s"] for r in records) / len(records), 2),
        "avg_model_calls": round(sum(r["model_calls"] for r in records) / len(records), 2),
    }


def write_report(records: list[dict], summary: dict, credentials: dict, label: str) -> Path:
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = RESULTS / f"{stamp}_{label}"
    meta = {"run_at": stamp, "label": label, "provider": credentials["provider"], "model": credentials["model"]}
    base.with_suffix(".json").write_text(json.dumps({"meta": meta, "summary": summary, "records": records},
                                                    indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines = [f"# Evaluation run {stamp} ({label})", "",
             f"Model: {credentials['provider']} / {credentials['model']} · data: data/ (course-provided)", "",
             "| Metric | Result |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in summary.items() if k != "by_category"]
    lines += ["", "| Category | Passed |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summary["by_category"].items()]
    lines += ["", "| ID | Category | Result | Latency | Calls | Tools | Failed checks |", "|---|---|---|---|---|---|---|"]
    for r in records:
        failed = "; ".join(f"{c['check']}: {c['detail']}" for c in r["checks"] if not c["pass"]) or ""
        lines.append(f"| {r['id']} | {r['category']} | {'PASS' if r['passed'] else 'FAIL'} | {r['latency_s']}s | "
                     f"{r['model_calls']} | {', '.join(c['name'] for c in r['tool_calls']) or '-'} | {failed.replace('|', '/')} |")
    lines += ["", "## Answers", ""]
    for r in records:
        lines += [f"### {r['id']} — {r['question']}", "", r["answer"] or f"_(error: {r['error']})_", ""]
    base.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    return base


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["dev", "heldout", "all"], default="dev")
    parser.add_argument("--ids", help="comma-separated question IDs")
    parser.add_argument("--label", help="name for the result files")
    args = parser.parse_args()
    facts = json.loads((HERE / "answer_key.json").read_text(encoding="utf-8"))
    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))["questions"]
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    elif args.set != "all":
        questions = [q for q in questions if q["set"] == args.set]
    records, credentials = asyncio.run(run(questions, facts))
    summary = summarise(records)
    path = write_report(records, summary, credentials, args.label or (args.ids and "selected") or args.set)
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nReport: {path.with_suffix('.md')}")


if __name__ == "__main__":
    main()
