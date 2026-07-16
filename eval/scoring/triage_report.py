# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cross-version triage report for skill evolution.

Turns a V0/V1 held-out comparison into the real story: how many SKILL-FIXABLE
failures evolution healed automatically, and an owner-routed backlog of the
failures it provably CANNOT fix by editing a skill (tool bugs -> ENG, missing
facts -> KNOWLEDGE, out-of-scope -> PRODUCT).

It re-attributes every non-meaningful session into a fixability taxonomy with a
focused LLM pass (the scorer's built-in attribution is coarse and dumps tool bugs
/ knowledge gaps into skill_gap). It does NOT re-score quality -- it reads the
usefulness verdicts the scorer already produced.

Usage:
    uv run python eval/scoring/triage_report.py --run-dir eval/runs/<run> \
        -o eval/runs/<run>/TRIAGE.md
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

from google.genai import types
from pydantic import BaseModel

from eval.scoring.llm_judge import JUDGE_MODEL, _get_client, load_scope_context

logger = logging.getLogger(__name__)

# Fixability taxonomy -> who owns the fix.
# skill_fixable is the only class evolution can fix by editing a SKILL.md.
CATEGORY_OWNER = {
    "skill_fixable": "EVOLUTION",
    "tool_bug": "ENG",
    "tool_gap": "ENG",
    "knowledge_gap": "KNOWLEDGE",
    "out_of_scope": "PRODUCT",
    "not_a_failure": "NONE",
}
VALID_CATEGORIES = tuple(CATEGORY_OWNER)
# Anything that is a real failure but NOT skill_fixable -> the routed backlog.
BACKLOG_CATEGORIES = ("tool_bug", "tool_gap", "knowledge_gap", "out_of_scope")
OWNER_ACTION = {
    "ENG": "fix/build a tool",
    "KNOWLEDGE": "add a fact to the knowledge base",
    "PRODUCT": "scope decision (allow/deny list)",
    "EVOLUTION": "next evolution round",
}


class TriageVerdict(BaseModel):
    """Structured output for the re-attribution pass."""
    category: str
    reason: str
    recommended_fix: str


ATTRIBUTION_PROMPT = """\
You are triaging a FAILED response from a multi-agent HR assistant. Your job is to
decide WHO can fix it by classifying the root cause into exactly one category.

The assistant is a supervisor that delegates to specialist tools/agents:
- policy_agent: company policy (PTO, sick leave, remote work, expenses, holidays,
  bereavement, jury duty, flex time).
- benefits_agent: employee benefits (health/dental/vision, HSA, 401k, parental &
  adoption leave, EAP, tuition reimbursement, short-term disability).
- hr_calculator: PTO/sick balance and working-day/date calculations.

Categories (pick the single best fit):
- skill_fixable: The agent HAD a tool and the data to answer, but misbehaved --
  failed to route, answered only part of a multi-topic question, announced it
  would gather info then stopped, asked permission instead of acting, or
  hallucinated despite a tool being available. A better instruction (skill) fixes
  this. THIS is what skill evolution can repair.
- tool_bug: A tool was actually called and RAN, but returned a wrong/implausible
  value (e.g. a calculator returns a number that contradicts the ground truth).
  Editing a skill cannot fix buggy tool logic. Owner: ENG.
- tool_gap: No tool or capability exists that could serve this request at all.
  Owner: ENG (build a tool).
- knowledge_gap: The right tool was used correctly, but a specific fact the user
  needs is simply absent from the underlying data/documents. Owner: KNOWLEDGE.
- out_of_scope: The question is outside what the assistant should handle; the
  correct behavior is a clean, polite decline. The failure is that it did NOT
  cleanly decline (it soft-failed, searched, or half-answered). Owner: PRODUCT.
- not_a_failure: On reflection the response is actually acceptable / the judge was
  too harsh.

Prefer skill_fixable ONLY when the tool+data were truly available and the agent
simply behaved wrong. If a number came back wrong from a calculation, that is
tool_bug, not skill_fixable. If a needed fact is missing from the data, that is
knowledge_gap, not skill_fixable.
{scope_context}

QUESTION: {question}

EXPECTED ANSWER (ground truth, may be empty for out-of-scope): {expected}

AGENT RESPONSE: {response}

SIGNALS from the scorer (for reference):
- usefulness verdict: {usefulness}
- tool_usage: {tool_usage}   correctness: {correctness}   scope_compliance: {scope}
- prior coarse attribution: {prior_attr}

Respond with: category, a one-sentence reason, and a concrete recommended_fix
(what the owner should change).
"""


def _load_report(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _index_sessions(report: dict) -> dict:
    """Map question -> session fields we need, keyed by exact question text."""
    out = {}
    for s in report.get("sessions", []):
        q = s.get("question", "")
        if not q:
            continue
        m = s.get("metrics", {})
        qs = s.get("quality_scores", {})
        out[q] = {
            "usefulness": (m.get("response_usefulness") or {}).get("category", "unknown"),
            "prior_attr": (m.get("failure_attribution") or {}).get("category", "-"),
            "response": s.get("response", "") or "",
            "expected": (s.get("golden_eval") or {}).get("expected_answer", "") or "",
            "tool_usage": (qs.get("tool_usage") or {}).get("score", "-"),
            "correctness": (qs.get("correctness") or {}).get("score", "-"),
            "scope": (qs.get("scope_compliance") or {}).get("score", "-"),
        }
    return out


async def _attribute(question: str, sess: dict, scope_ctx: str, client, sem) -> dict:
    prompt = ATTRIBUTION_PROMPT.format(
        scope_context=scope_ctx,
        question=question,
        expected=(sess["expected"] or "(none)")[:400],
        response=(sess["response"] or "(empty)")[:1200],
        usefulness=sess["usefulness"],
        tool_usage=sess["tool_usage"],
        correctness=sess["correctness"],
        scope=sess["scope"],
        prior_attr=sess["prior_attr"],
    )
    async with sem:
        try:
            result = await asyncio.to_thread(
                client.models.generate_content,
                model=JUDGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=TriageVerdict,
                    temperature=0.0,
                ),
            )
            data = json.loads(result.text)
            cat = str(data.get("category", "skill_fixable")).lower().strip()
            if cat not in VALID_CATEGORIES:
                cat = "skill_fixable"
            return {
                "category": cat,
                "reason": data.get("reason", ""),
                "recommended_fix": data.get("recommended_fix", ""),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("Attribution failed for %r: %s", question[:60], e)
            return {"category": "skill_fixable", "reason": f"attribution error: {e}",
                    "recommended_fix": ""}


async def _classify_failures(index: dict, scope_ctx: str, concurrency: int) -> dict:
    """Re-attribute every non-meaningful session in an index. Returns q -> verdict."""
    client = _get_client()
    sem = asyncio.Semaphore(concurrency)
    failing = {q: s for q, s in index.items() if s["usefulness"] != "meaningful"}
    verdicts = await asyncio.gather(
        *(_attribute(q, s, scope_ctx, client, sem) for q, s in failing.items())
    )
    return dict(zip(failing.keys(), verdicts))


def _truncate(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def build_triage(v0: dict, v1: dict, concurrency: int) -> dict:
    """Run the full triage; returns a JSON-serializable result dict."""
    v0_idx = _index_sessions(v0)
    v1_idx = _index_sessions(v1)
    scope_ctx = load_scope_context()

    v0_attr, v1_attr = asyncio.run(_gather_both(v0_idx, v1_idx, scope_ctx, concurrency))

    # --- Recovery on the skill-addressable slice (denominator = V0 skill_fixable) ---
    skill_addressable = [q for q, v in v0_attr.items() if v["category"] == "skill_fixable"]
    recovered, not_recovered = [], []
    for q in skill_addressable:
        now = v1_idx.get(q, {}).get("usefulness")
        (recovered if now == "meaningful" else not_recovered).append(q)
    denom = len(skill_addressable)
    recovery_rate = round(100.0 * len(recovered) / denom, 1) if denom else 0.0

    # --- Routed backlog = V1 non-meaningful, non-skill failures ---
    tickets = []
    skill_residual = []  # skill_fixable but still failing in V1 -> next round
    for q, v in v1_attr.items():
        cat = v["category"]
        if cat == "not_a_failure":
            continue
        ticket = {
            "question": q,
            "category": cat,
            "owner": CATEGORY_OWNER.get(cat, "ENG"),
            "reason": v["reason"],
            "recommended_fix": v["recommended_fix"],
            "expected": v1_idx[q]["expected"],
            "response": v1_idx[q]["response"],
        }
        if cat == "skill_fixable":
            skill_residual.append(ticket)
        elif cat in BACKLOG_CATEGORIES:
            tickets.append(ticket)

    def _summary(report):
        return report.get("summary", {})

    backlog_by_owner = {}
    for t in tickets:
        backlog_by_owner.setdefault(t["owner"], []).append(t)

    return {
        "summary": {
            "v0_meaningful_rate": _summary(v0).get("meaningful_rate"),
            "v1_meaningful_rate": _summary(v1).get("meaningful_rate"),
            "skill_addressable": denom,
            "recovered": len(recovered),
            "recovery_rate": recovery_rate,
            "backlog_total": len(tickets),
            "backlog_by_category": {
                c: sum(1 for t in tickets if t["category"] == c) for c in BACKLOG_CATEGORIES
            },
            "skill_residual": len(skill_residual),
        },
        "backlog_by_owner": backlog_by_owner,
        "skill_residual": skill_residual,
    }


async def _gather_both(v0_idx, v1_idx, scope_ctx, concurrency):
    return await asyncio.gather(
        _classify_failures(v0_idx, scope_ctx, concurrency),
        _classify_failures(v1_idx, scope_ctx, concurrency),
    )


def render_markdown(t: dict) -> str:
    s = t["summary"]
    L = []
    L.append("# Skill Evolution — Triage Report\n")
    L.append(
        f"**Held-out meaningful rate:** V0 {s['v0_meaningful_rate']}% "
        f"→ V1 {s['v1_meaningful_rate']}%\n"
    )
    L.append(
        f"## Evolution auto-healed {s['recovered']}/{s['skill_addressable']} "
        f"skill-fixable failures ({s['recovery_rate']}%)\n"
    )
    if s["skill_residual"]:
        L.append(
            f"_{s['skill_residual']} skill-fixable failure(s) not yet recovered "
            f"→ routed to EVOLUTION (next round)._\n"
        )

    bc = s["backlog_by_category"]
    L.append(
        f"## Cannot be fixed by skill evolution → routed backlog "
        f"({s['backlog_total']})\n"
    )
    L.append(
        f"tool bugs: {bc['tool_bug']} · missing tools: {bc['tool_gap']} · "
        f"knowledge gaps: {bc['knowledge_gap']} · out-of-scope: {bc['out_of_scope']}\n"
    )

    owner_titles = {
        "ENG": "ENG — tool bug / missing tool",
        "KNOWLEDGE": "KNOWLEDGE — add a fact to the knowledge base",
        "PRODUCT": "PRODUCT — scope decision (allow/deny list)",
    }
    for owner in ("ENG", "KNOWLEDGE", "PRODUCT"):
        items = t["backlog_by_owner"].get(owner, [])
        if not items:
            continue
        L.append(f"### {owner_titles[owner]} ({len(items)})\n")
        for it in items:
            L.append(f"- **Q:** {_truncate(it['question'], 160)}")
            L.append(f"  - root cause ({it['category']}): {_truncate(it['reason'], 200)}")
            L.append(f"  - fix: {_truncate(it['recommended_fix'], 200)}")
            if it["expected"]:
                L.append(f"  - expected: {_truncate(it['expected'], 140)}")
            L.append(f"  - got: {_truncate(it['response'], 140)}")
        L.append("")

    if t["skill_residual"]:
        L.append("### EVOLUTION — skill failures not yet recovered "
                 f"({len(t['skill_residual'])})\n")
        for it in t["skill_residual"]:
            L.append(f"- **Q:** {_truncate(it['question'], 160)}")
            L.append(f"  - {_truncate(it['reason'], 200)}")
        L.append("")

    return "\n".join(L)


def _gh(args: list[str]) -> tuple[int, str]:
    """Run a gh command; return (rc, stdout). Never raises."""
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True)
        return p.returncode, (p.stdout or "").strip() or (p.stderr or "").strip()
    except FileNotFoundError:
        return 127, "gh not found"


# Owner -> a GitHub label color (best-effort; ignored if labels can't be created).
_OWNER_LABEL = {"ENG": "eng", "KNOWLEDGE": "knowledge", "PRODUCT": "product"}
_BACKLOG_LABEL = "evolution-backlog"


def _ensure_labels(dry_run: bool) -> None:
    if dry_run:
        return
    specs = [(_BACKLOG_LABEL, "5319e7"), ("eng", "d73a4a"),
             ("knowledge", "0e8a16"), ("product", "1d76db")]
    for name, color in specs:
        _gh(["label", "create", name, "--color", color,
             "--description", "Skill-evolution triage", "--force"])


def _existing_titles() -> set:
    rc, out = _gh(["issue", "list", "--label", _BACKLOG_LABEL, "--state", "all",
                   "--limit", "300", "--json", "title"])
    if rc != 0:
        return set()
    try:
        return {i["title"] for i in json.loads(out)}
    except (json.JSONDecodeError, KeyError, TypeError):
        return set()


def file_backlog_issues(t: dict, run_name: str, dry_run: bool) -> dict:
    """Create one GitHub issue per non-fixable backlog ticket, routed by owner.

    Idempotent: skips tickets whose title already exists under the backlog label.
    Records created/skipped URLs back into the triage dict. Returns the dict.
    """
    _ensure_labels(dry_run)
    existing = set() if dry_run else _existing_titles()
    filed = []
    for owner in ("ENG", "KNOWLEDGE", "PRODUCT"):
        for it in t["backlog_by_owner"].get(owner, []):
            q = _truncate(it["question"], 80)
            title = f"[{_BACKLOG_LABEL}][{owner}] {q}"
            body = (
                f"**Evolution cannot fix this by editing a skill — routed to {owner}.**\n\n"
                f"- **Question:** {it['question']}\n"
                f"- **Root cause ({it['category']}):** {it['reason']}\n"
                f"- **Recommended fix:** {it['recommended_fix']} "
                f"_({OWNER_ACTION.get(owner, '')})_\n"
                f"- **Expected:** {it['expected'] or '(out-of-scope: clean decline)'}\n"
                f"- **Agent got:** {_truncate(it['response'], 300)}\n\n"
                f"_Source: skill-evolution triage, run `{run_name}`._"
            )
            labels = f"{_BACKLOG_LABEL},{_OWNER_LABEL[owner]}"
            if title in existing:
                filed.append({"title": title, "status": "exists"})
                continue
            if dry_run:
                print(f"[DRY RUN] would file ({labels}): {title}")
                filed.append({"title": title, "status": "dry-run"})
                continue
            rc, out = _gh(["issue", "create", "--title", title, "--body", body,
                           "--label", labels])
            if rc == 0 and out.startswith("http"):
                print(f"  filed {owner}: {out}")
                filed.append({"title": title, "status": "created", "url": out})
            else:
                # Retry without labels in case label creation was not permitted.
                rc2, out2 = _gh(["issue", "create", "--title", title, "--body", body])
                if rc2 == 0 and out2.startswith("http"):
                    print(f"  filed {owner} (no labels): {out2}")
                    filed.append({"title": title, "status": "created", "url": out2})
                else:
                    logger.warning("Failed to file issue %r: %s", title, out or out2)
                    filed.append({"title": title, "status": "failed", "error": out or out2})
    t["filed_issues"] = filed
    created = sum(1 for f in filed if f["status"] == "created")
    print(f"  Backlog issues: {created} created, "
          f"{sum(1 for f in filed if f['status']=='exists')} already existed, "
          f"{sum(1 for f in filed if f['status']=='dry-run')} dry-run")
    return t


def render_headline(t: dict) -> str:
    s = t["summary"]
    bc = s["backlog_by_category"]
    return (
        f"  Triage: auto-healed {s['recovered']}/{s['skill_addressable']} "
        f"skill failures ({s['recovery_rate']}%); "
        f"backlog {s['backlog_total']} "
        f"(ENG {bc['tool_bug'] + bc['tool_gap']}, "
        f"KNOWLEDGE {bc['knowledge_gap']}, PRODUCT {bc['out_of_scope']})"
    )


def main():
    ap = argparse.ArgumentParser(description="Cross-version skill-evolution triage report.")
    ap.add_argument("--run-dir", help="Run dir containing v0_test_report.json + v1_test_report.json")
    ap.add_argument("--v0", help="V0 held-out report JSON (overrides --run-dir)")
    ap.add_argument("--v1", help="V1 held-out report JSON (overrides --run-dir)")
    ap.add_argument("-o", "--output", help="Output TRIAGE.md path")
    ap.add_argument("--json", dest="json_out", help="Output triage.json path")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--file-issues", action="store_true",
                    help="File a GitHub issue per non-fixable backlog ticket (gh).")
    ap.add_argument("--issues-dry-run", action="store_true",
                    help="With --file-issues: print issues instead of creating them.")
    args = ap.parse_args()

    if args.run_dir:
        rd = Path(args.run_dir)
        v0_path = Path(args.v0) if args.v0 else rd / "v0_test_report.json"
        v1_path = Path(args.v1) if args.v1 else rd / "v1_test_report.json"
        out_md = Path(args.output) if args.output else rd / "TRIAGE.md"
        out_json = Path(args.json_out) if args.json_out else rd / "triage.json"
    else:
        if not (args.v0 and args.v1):
            ap.error("provide --run-dir, or both --v0 and --v1")
        v0_path, v1_path = Path(args.v0), Path(args.v1)
        out_md = Path(args.output) if args.output else Path("TRIAGE.md")
        out_json = Path(args.json_out) if args.json_out else out_md.with_suffix(".json")

    logging.basicConfig(level=logging.INFO)
    v0, v1 = _load_report(v0_path), _load_report(v1_path)
    t = build_triage(v0, v1, args.concurrency)

    if args.file_issues:
        run_name = Path(args.run_dir).name if args.run_dir else out_md.parent.name
        t = file_backlog_issues(t, run_name, dry_run=args.issues_dry_run)

    out_md.write_text(render_markdown(t))
    out_json.write_text(json.dumps(t, indent=2))
    print(render_headline(t))
    print(f"  Triage report: {out_md}")
    print(f"  Triage JSON:   {out_json}")


if __name__ == "__main__":
    main()
