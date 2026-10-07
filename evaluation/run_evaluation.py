"""
SmartLogix evaluation harness - produces the numbers for the report's
"Evaluation Results" section.

Four suites, one per part of the system:

    intake      Intake Agent: issue-type classification + order-ID extraction  (LLM)
    retrieval   Policy Agent IR: Precision@k, Recall@k, Hit@k, MRR             (no LLM)
    injection   Input sanitizer: attack block rate vs. false-positive rate     (no LLM)
    resolution  Investigation + Resolution: fault accuracy, refund-decision
                accuracy, reply/decision consistency                           (LLM)

Usage (from the project root, venv active):

    python -m evaluation.run_evaluation                         # all suites
    python -m evaluation.run_evaluation --suites retrieval injection   # offline only
    python -m evaluation.run_evaluation --suites resolution --per-class 5

Each run writes evaluation/results/run-<timestamp>/ containing summary.json,
report.md (tables ready to paste into the report) and one *_predictions.csv
per suite so every number can be traced back to individual cases.

The retrieval suite needs the ChromaDB index (python -m src.policy_service.ingest);
it does not need the Policy Agent service to be running.
"""

import argparse
import csv
import json
import random
import subprocess
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from evaluation.metrics import (
    accuracy, binary_metrics, classification_report, confusion_matrix,
    hit_at_k, precision_at_k, recall_at_k, reciprocal_rank, safe_div, wilson_interval,
)
from src.config import DATA_DIR, GROQ_MODEL

DATASETS_DIR = Path(__file__).parent / "datasets"
RESULTS_DIR = Path(__file__).parent / "results"
ALL_SUITES = ["intake", "retrieval", "injection", "resolution"]

ISSUE_LABELS = ["damaged", "late", "lost", "wrong_address", "policy_question", "new_quote", "other"]
FAULT_LABELS = ["warehouse", "courier", "weather", "customer", "unclear"]
ACTION_LABELS = ["full_refund", "partial_refund", "no_refund", "escalated_to_human"]
STATUS_TO_ISSUE = {"Damaged": "damaged", "Delayed": "late", "Lost": "lost"}

# Every agent call made by the evaluation is logged under this session id, so
# evaluation traffic can be filtered out of logs/agent_activity.log.
SESSION_ID = "eval-" + datetime.now().strftime("%Y%m%d-%H%M%S")


# --- helpers -----------------------------------------------------------------

def load_jsonl(name: str) -> list[dict]:
    with open(DATASETS_DIR / name, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def rate(successes: int, n: int) -> dict:
    low, high = wilson_interval(successes, n)
    return {"value": safe_div(successes, n), "n": n, "ci95": [low, high]}


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def fmt_rate(r: dict) -> str:
    return f"{pct(r['value'])} (n={r['n']}, 95% CI {pct(r['ci95'][0])}-{pct(r['ci95'][1])})"


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


class CallRecorder:
    """Wraps an LLM function to keep its last raw output and any exception,
    so evaluation can tell an API failure apart from a genuine wrong answer
    (the agents themselves swallow LLM errors and fall back gracefully)."""

    def __init__(self, fn):
        self.fn = fn
        self.reset()

    def reset(self):
        self.last_output = None
        self.last_error = None

    def __call__(self, *args, **kwargs):
        try:
            self.last_output = self.fn(*args, **kwargs)
            return self.last_output
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            raise


# --- Suite 1: Intake ---------------------------------------------------------

def run_intake_suite(delay: float) -> tuple[dict, list[dict]]:
    from src.agents.intake_agent import run_intake_agent

    rows = []
    for case in load_jsonl("intake_cases.jsonl"):
        error, pred_issue, pred_id = "", None, None
        try:
            out = run_intake_agent(case["text"], session_id=SESSION_ID)
            pred_issue = out.issue_type if out.status == "ok" else "blocked"
            pred_id = out.order_id
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        rows.append({
            "id": case["id"], "text": case["text"],
            "expected_issue": case["issue_type"], "predicted_issue": pred_issue,
            "issue_correct": pred_issue == case["issue_type"],
            "expected_order_id": case["order_id"], "predicted_order_id": pred_id,
            "order_id_correct": pred_id == case["order_id"],
            "error": error,
        })
        print(f"  intake {case['id']}: {case['issue_type']:>15} -> {pred_issue}")
        time.sleep(delay)

    scored = [r for r in rows if not r["error"]]
    y_true = [r["expected_issue"] for r in scored]
    y_pred = [r["predicted_issue"] for r in scored]
    report = classification_report(y_true, y_pred, ISSUE_LABELS)
    no_id_cases = [r for r in scored if r["expected_order_id"] is None]

    summary = {
        "cases": len(rows),
        "errors": len(rows) - len(scored),
        "blocked_by_sanitizer": sum(r["predicted_issue"] == "blocked" for r in scored),
        "issue_type_accuracy": rate(sum(r["issue_correct"] for r in scored), len(scored)),
        "issue_type_macro_f1": report["macro"]["f1"],
        "per_class": report["per_class"],
        "confusion_matrix": {"labels": ISSUE_LABELS,
                             "matrix": confusion_matrix(y_true, y_pred, ISSUE_LABELS)},
        "order_id_exact_match": rate(sum(r["order_id_correct"] for r in scored), len(scored)),
        "order_id_hallucination_rate": rate(
            sum(r["predicted_order_id"] is not None for r in no_id_cases), len(no_id_cases)),
    }
    return summary, rows


# --- Suite 2: Retrieval ------------------------------------------------------

def _is_heading_only(chunk: str) -> bool:
    lines = [l for l in chunk.strip().splitlines() if l.strip()]
    return len(lines) == 1 and lines[0].lstrip().startswith("#")


def run_retrieval_suite(ks: list[int]) -> tuple[dict, list[dict]]:
    from src.policy_service.rag import get_collection, retrieve

    if get_collection().count() == 0:
        raise RuntimeError("ChromaDB index is empty - run: python -m src.policy_service.ingest")

    max_k = max(ks)
    rows, per_query = [], []
    for case in load_jsonl("retrieval_cases.jsonl"):
        chunks, sources = retrieve(case["query"], k=max_k)
        relevant = set(case["relevant"])
        per_query.append((sources, relevant, chunks))
        row = {"id": case["id"], "query": case["query"], "relevant": "|".join(case["relevant"]),
               "retrieved_sources": "|".join(sources)}
        for k in ks:
            row[f"precision@{k}"] = round(precision_at_k(sources, relevant, k), 4)
            row[f"hit@{k}"] = hit_at_k(sources, relevant, k)
        row["reciprocal_rank"] = round(reciprocal_rank(sources, relevant), 4)
        row["top1_chunk"] = (chunks[0] if chunks else "").replace("\n", " ")[:160]
        rows.append(row)

    n = len(per_query)
    by_k = {}
    for k in ks:
        heading_hits = sum(_is_heading_only(c) for _, _, chunks in per_query for c in chunks[:k])
        by_k[str(k)] = {
            "precision": safe_div(sum(precision_at_k(s, r, k) for s, r, _ in per_query), n),
            "recall": safe_div(sum(recall_at_k(s, r, k) for s, r, _ in per_query), n),
            "hit_rate": safe_div(sum(hit_at_k(s, r, k) for s, r, _ in per_query), n),
            "heading_only_chunk_share": safe_div(heading_hits, sum(min(k, len(c)) for _, _, c in per_query)),
        }
    summary = {
        "queries": n,
        "index_chunks": get_collection().count(),
        "by_k": by_k,
        "mrr": safe_div(sum(reciprocal_rank(s, r) for s, r, _ in per_query), n),
    }
    return summary, rows


# --- Suite 3: Prompt-injection filter -----------------------------------------

def run_injection_suite() -> tuple[dict, list[dict]]:
    from src.security.sanitize import sanitize_input

    rows = []
    for case in load_jsonl("injection_cases.jsonl"):
        _, blocked, reasons = sanitize_input(case["text"])
        rows.append({
            "id": case["id"], "label": case["label"], "category": case["category"],
            "text": case["text"], "blocked": blocked,
            "correct": blocked == (case["label"] == "attack"),
            "matched_patterns": " | ".join(reasons),
        })

    y_true = [r["label"] == "attack" for r in rows]
    y_pred = [r["blocked"] for r in rows]
    by_category = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["label"] == "attack":
            by_category[r["category"]][0] += r["blocked"]
            by_category[r["category"]][1] += 1

    attacks = [r for r in rows if r["label"] == "attack"]
    benign = [r for r in rows if r["label"] == "benign"]
    summary = {
        "attacks": len(attacks),
        "benign": len(benign),
        "block_rate": rate(sum(r["blocked"] for r in attacks), len(attacks)),
        "false_positive_rate": rate(sum(r["blocked"] for r in benign), len(benign)),
        "binary": binary_metrics(y_true, y_pred),
        "block_rate_by_category": {c: rate(b, t) for c, (b, t) in sorted(by_category.items())},
        "missed_attacks": [r["id"] for r in attacks if not r["blocked"]],
        "false_positives": [r["id"] for r in benign if r["blocked"]],
    }
    return summary, rows


# --- Suite 4: Investigation + Resolution ---------------------------------------

def reference_fault(issue: str, evidence: dict) -> str:
    """Reference label written from the policy documents + the data
    generator's causal rules, independently of the LLM. The Investigation
    Agent is scored on how faithfully it reaches the same conclusion from the
    same evidence."""
    from src.agents.investigation_agent import HIGH_COURIER_DAMAGE_COUNT, HIGH_COURIER_DELAY_COUNT

    if issue == "damaged":
        if evidence["item_requires_fragile_packaging"] and evidence["packaging_label"] != "Fragile":
            return "warehouse"
        if evidence["courier_past_damage_count"] >= HIGH_COURIER_DAMAGE_COUNT:
            return "courier"
        if evidence["weather_flag"]:
            return "weather"
        return "unclear"
    if issue == "late":
        if evidence["weather_flag"]:
            return "weather"
        if evidence["courier_past_delay_count"] >= HIGH_COURIER_DELAY_COUNT:
            return "courier"
        return "unclear"
    if issue == "lost":
        return "courier" if evidence["order_status"] == "Lost" else "unclear"
    return "unclear"


def _sample_orders(per_class: int, seed: int) -> list[tuple[str, str]]:
    import pandas as pd

    orders = pd.read_csv(DATA_DIR / "orders.csv")
    rng = random.Random(seed)
    sample = []
    for status, issue in STATUS_TO_ISSUE.items():
        ids = sorted(orders.loc[orders["status"] == status, "order_id"])
        sample += [(oid, issue) for oid in rng.sample(ids, min(per_class, len(ids)))]
    return sample


def run_resolution_suite(per_class: int, seed: int, delay: float) -> tuple[dict, list[dict]]:
    from src.agents import investigation_agent, resolution_agent
    from src.agents.decision_rules import check_reply_consistency, decide
    from src.agents.schemas import IntakeOutput, PolicyOutput
    from src.coordinator import POLICY_QUERIES
    from src.policy_service.rag import retrieve

    inv_rec = CallRecorder(investigation_agent.call_llm_json)
    res_rec = CallRecorder(resolution_agent.call_llm)
    rows = []

    with patch.object(investigation_agent, "call_llm_json", inv_rec), \
         patch.object(resolution_agent, "call_llm", res_rec):
        for order_id, issue in _sample_orders(per_class, seed):
            inv_rec.reset()
            res_rec.reset()
            # Intake is evaluated separately; start from a correct intake so
            # this suite isolates Investigation + Resolution.
            intake = IntakeOutput(status="ok", order_id=order_id, issue_type=issue,
                                  summary=f"Customer reports order {order_id} as {issue}.")
            investigation = investigation_agent.run_investigation_agent(intake, SESSION_ID)
            time.sleep(delay)

            chunks, sources = retrieve(POLICY_QUERIES[issue], k=3)
            policy = PolicyOutput(answer="", sources=list(dict.fromkeys(sources)), chunks=chunks)
            resolution = resolution_agent.run_resolution_agent(intake, investigation, policy, SESSION_ID)
            time.sleep(delay)

            expected_fault = reference_fault(issue, investigation.evidence_used)
            expected_action = decide(issue, expected_fault).action
            raw_reply = res_rec.last_output or ""
            rows.append({
                "order_id": order_id,
                "issue_type": issue,
                "expected_fault": expected_fault,
                "predicted_fault": investigation.likely_fault,
                "fault_correct": investigation.likely_fault == expected_fault,
                "confidence": investigation.confidence,
                "expected_action": expected_action,
                "predicted_action": resolution.action,
                "action_correct": resolution.action == expected_action,
                "llm_reply_consistent": bool(raw_reply) and not check_reply_consistency(
                    resolution.action, issue, raw_reply),
                "final_reply_consistent": not check_reply_consistency(
                    resolution.action, issue, resolution.final_answer),
                "reply_source": resolution.reply_source,
                "investigation_llm_error": inv_rec.last_error or "",
                "resolution_llm_error": res_rec.last_error or "",
                "reasoning": investigation.reasoning,
                "evidence": json.dumps(investigation.evidence_used, default=str),
                "final_answer": resolution.final_answer,
            })
            print(f"  resolution {order_id} ({issue}): fault {expected_fault} -> "
                  f"{investigation.likely_fault}, action {resolution.action}, reply {resolution.reply_source}")

    scored = [r for r in rows if not r["investigation_llm_error"]]
    y_true = [r["expected_fault"] for r in scored]
    y_pred = [r["predicted_fault"] for r in scored]
    report = classification_report(y_true, y_pred, FAULT_LABELS)
    llm_replies = [r for r in rows if not r["resolution_llm_error"]]
    late = [r for r in scored if r["issue_type"] == "late"]

    by_issue = {}
    for issue in STATUS_TO_ISSUE.values():
        subset = [r for r in scored if r["issue_type"] == issue]
        by_issue[issue] = {
            "fault_accuracy": rate(sum(r["fault_correct"] for r in subset), len(subset)),
            "action_accuracy": rate(sum(r["action_correct"] for r in subset), len(subset)),
        }

    summary = {
        "cases": len(rows),
        "llm_errors": {"investigation": len(rows) - len(scored),
                       "resolution": len(rows) - len(llm_replies)},
        "fault_accuracy": rate(sum(r["fault_correct"] for r in scored), len(scored)),
        "fault_macro_f1": report["macro"]["f1"],
        "fault_per_class": report["per_class"],
        "fault_confusion_matrix": {"labels": FAULT_LABELS,
                                   "matrix": confusion_matrix(y_true, y_pred, FAULT_LABELS)},
        "action_accuracy": rate(sum(r["action_correct"] for r in scored), len(scored)),
        "escalation_rate": rate(sum(r["predicted_action"] == "escalated_to_human" for r in rows), len(rows)),
        "llm_reply_consistency": rate(sum(r["llm_reply_consistent"] for r in llm_replies), len(llm_replies)),
        "final_reply_consistency": rate(sum(r["final_reply_consistent"] for r in rows), len(rows)),
        "template_fallback_rate": rate(sum(r["reply_source"] == "template" for r in rows), len(rows)),
        "late_orders_blamed_on_packaging": rate(
            sum(r["predicted_fault"] == "warehouse" for r in late), len(late)),
        "by_issue": by_issue,
    }
    return summary, rows


# --- Report ------------------------------------------------------------------

def _matrix_table(labels: list[str], matrix: list[list[int]]) -> list[str]:
    lines = ["| true \\ predicted | " + " | ".join(labels) + " |",
             "|---" * (len(labels) + 1) + "|"]
    for label, row in zip(labels, matrix):
        lines.append(f"| **{label}** | " + " | ".join(str(v) for v in row) + " |")
    return lines


def _per_class_table(per_class: dict) -> list[str]:
    lines = ["| Class | Precision | Recall | F1 | Support |", "|---|---|---|---|---|"]
    for label, m in per_class.items():
        if m["support"] or m["precision"]:
            lines.append(f"| {label} | {m['precision']:.2f} | {m['recall']:.2f} | "
                         f"{m['f1']:.2f} | {m['support']} |")
    return lines


def build_report(meta: dict, results: dict) -> str:
    out = ["# SmartLogix - Evaluation Results", "",
           f"- Run: `{meta['run_id']}`  |  Model: `{meta['model']}`  |  Commit: `{meta['commit']}`",
           f"- Suites: {', '.join(results)}", ""]

    if "intake" in results:
        s = results["intake"]
        out += ["## 1. Intake Agent - NLU (issue classification + entity extraction)", "",
                "| Metric | Result |", "|---|---|",
                f"| Issue-type accuracy | {fmt_rate(s['issue_type_accuracy'])} |",
                f"| Issue-type macro-F1 | {s['issue_type_macro_f1']:.3f} |",
                f"| Order-ID exact match | {fmt_rate(s['order_id_exact_match'])} |",
                f"| Order-ID hallucination rate (no ID in message) | {fmt_rate(s['order_id_hallucination_rate'])} |",
                f"| Blocked by sanitizer (all benign) | {s['blocked_by_sanitizer']} |",
                f"| LLM errors | {s['errors']} |", "", "**Per class**", ""]
        out += _per_class_table(s["per_class"]) + ["", "**Confusion matrix**", ""]
        out += _matrix_table(s["confusion_matrix"]["labels"], s["confusion_matrix"]["matrix"]) + [""]

    if "retrieval" in results:
        s = results["retrieval"]
        out += ["## 2. Policy Agent - Information Retrieval (ChromaDB)", "",
                f"{s['queries']} labelled queries, {s['index_chunks']} indexed chunks; "
                "relevance judged at document level.", "",
                "| k | Precision@k | Recall@k | Hit@k | Heading-only chunks in top-k |",
                "|---|---|---|---|---|"]
        for k, m in s["by_k"].items():
            out.append(f"| {k} | {m['precision']:.3f} | {m['recall']:.3f} | {m['hit_rate']:.3f} | "
                       f"{pct(m['heading_only_chunk_share'])} |")
        out += ["", f"**MRR:** {s['mrr']:.3f}", ""]

    if "injection" in results:
        s = results["injection"]
        b = s["binary"]
        out += ["## 3. Security - Prompt-injection filter", "",
                f"{s['attacks']} attack prompts, {s['benign']} benign prompts "
                "(including benign messages that share wording with attacks).", "",
                "| Metric | Result |", "|---|---|",
                f"| Block rate (recall on attacks) | {fmt_rate(s['block_rate'])} |",
                f"| False-positive rate (benign blocked) | {fmt_rate(s['false_positive_rate'])} |",
                f"| Precision | {b['precision']:.3f} |",
                f"| F1 | {b['f1']:.3f} |",
                f"| TP / FP / TN / FN | {b['tp']} / {b['fp']} / {b['tn']} / {b['fn']} |",
                "", "| Attack category | Block rate |", "|---|---|"]
        for cat, r in s["block_rate_by_category"].items():
            out.append(f"| {cat} | {pct(r['value'])} ({round(r['value'] * r['n'])}/{r['n']}) |")
        out += ["", f"Missed attacks: {', '.join(s['missed_attacks']) or 'none'}  ",
                f"False positives: {', '.join(s['false_positives']) or 'none'}", ""]

    if "resolution" in results:
        s = results["resolution"]
        out += ["## 4. Investigation + Resolution Agents - decision quality", "",
                f"{s['cases']} real orders (stratified by Damaged / Delayed / Lost status). "
                "Reference fault labels follow the policy documents and the data "
                "generator's causal rules.", "",
                "| Metric | Result |", "|---|---|",
                f"| Fault-attribution accuracy | {fmt_rate(s['fault_accuracy'])} |",
                f"| Fault macro-F1 | {s['fault_macro_f1']:.3f} |",
                f"| Refund-decision accuracy | {fmt_rate(s['action_accuracy'])} |",
                f"| Escalated to human | {fmt_rate(s['escalation_rate'])} |",
                f"| LLM reply consistent with decision (before guard) | {fmt_rate(s['llm_reply_consistency'])} |",
                f"| Final reply consistent with decision (after guard) | {fmt_rate(s['final_reply_consistency'])} |",
                f"| Template fallback used | {fmt_rate(s['template_fallback_rate'])} |",
                f"| Late orders blamed on packaging (should be 0) | {fmt_rate(s['late_orders_blamed_on_packaging'])} |",
                f"| LLM errors (investigation / resolution) | {s['llm_errors']['investigation']} / {s['llm_errors']['resolution']} |",
                "", "| Issue type | Fault accuracy | Decision accuracy |", "|---|---|---|"]
        for issue, m in s["by_issue"].items():
            out.append(f"| {issue} | {fmt_rate(m['fault_accuracy'])} | {fmt_rate(m['action_accuracy'])} |")
        out += ["", "**Fault confusion matrix**", ""]
        out += _matrix_table(s["fault_confusion_matrix"]["labels"], s["fault_confusion_matrix"]["matrix"]) + [""]

    out += ["## Notes on validity", "",
            "- Test sets are small and hand-written by the team; the 95% confidence "
            "intervals (Wilson) show how much each number could move.",
            "- All order data is synthetic (data/generate_data.py, fixed seed).",
            "- The injection suite measures the pattern filter only, not how the LLM "
            "behaves when an attack gets past it.", ""]
    return "\n".join(out)


# --- CLI ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SmartLogix evaluation suites.")
    parser.add_argument("--suites", nargs="+", choices=ALL_SUITES, default=ALL_SUITES)
    parser.add_argument("--k", nargs="+", type=int, default=[1, 3, 5],
                        help="cut-offs for retrieval metrics (default: 1 3 5)")
    parser.add_argument("--per-class", type=int, default=10,
                        help="orders sampled per status for the resolution suite (default: 10)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds to wait between LLM calls, to stay under Groq rate limits")
    args = parser.parse_args()

    run_id = SESSION_ID.replace("eval-", "run-")
    out_dir = RESULTS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    started = time.time()
    for suite in [s for s in ALL_SUITES if s in args.suites]:
        print(f"\n== {suite} ==")
        if suite == "intake":
            summary, rows = run_intake_suite(args.delay)
        elif suite == "retrieval":
            summary, rows = run_retrieval_suite(sorted(set(args.k)))
        elif suite == "injection":
            summary, rows = run_injection_suite()
        else:
            summary, rows = run_resolution_suite(args.per_class, args.seed, args.delay)
        results[suite] = summary
        write_csv(out_dir / f"{suite}_predictions.csv", rows)

    meta = {"run_id": run_id, "session_id": SESSION_ID, "model": GROQ_MODEL,
            "commit": git_commit(), "args": vars(args),
            "duration_seconds": round(time.time() - started, 1)}
    (out_dir / "summary.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=2), encoding="utf-8")
    report = build_report(meta, results)
    (out_dir / "report.md").write_text(report, encoding="utf-8")

    print("\n" + report)
    print(f"\nSaved to {out_dir}")


if __name__ == "__main__":
    main()
