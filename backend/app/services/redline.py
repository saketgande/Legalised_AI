"""The inbound redline engine — the hybrid core.

Given a counterparty's NDA (their paper, we are the Recipient), segment it into
clauses, classify each against the playbook, and run two kinds of checks:

  * DETERMINISTIC — the things LLMs get wrong and that cost money: parse the
    actual liability cap / term in months and compare to our floor; detect the
    governing-law jurisdiction; check a mandatory clause is present at all.
  * SEMANTIC — a meaning-level read (e.g. "is the confidentiality carve-out
    present?"). Heuristic today; the LLM plugs in at `semantic_*` with no change
    to callers, so the demo runs with no API key.

Every finding becomes a ProposedChange in PENDING state — nothing mutates the
document until a human approves it.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Clause,
    Counterparty,
    Document,
    DocumentVersion,
    PlaybookRule,
    ProposedChange,
    Request,
    ReviewRun,
)

# ————————————————————— policy (mirrors the playbook) —————————————————————
LIABILITY_CAP_FLOOR_MONTHS = 12
TERM_MAX_MONTHS = 24
ACCEPTABLE_JURISDICTIONS = {"Delaware", "New York", "California"}

CLAUSE_KEYWORDS: dict[str, list[str]] = {
    "confidential_information_definition": ['confidential information means', 'definition of confidential', '"confidential information"'],
    "purpose": ["purpose", "solely for"],
    "confidentiality_obligations": ["obligations of confiden", "hold in confidence", "shall not disclose", "strict confidence"],
    "exclusions": ["exclusions", "does not include", "publicly available"],
    "term": ["term", "survival", "remain in effect", "duration", "in effect for"],
    "return_destruction": ["return or destr", "return", "destroy", "destruction"],
    "no_license": ["no license", "as is", "warranty"],
    "injunctive_relief": ["injunctive", "equitable relief", "irreparable"],
    "governing_law": ["governing law", "governed by", "jurisdiction"],
    "limitation_of_liability": ["limitation of liability", "liability"],
    "assignment": ["assignment", "assign"],
    "entire_agreement": ["entire agreement", "amendment", "notices"],
}

_JURISDICTIONS = {
    "delaware": "Delaware", "new york": "New York", "california": "California",
    "england": "England & Wales", "wales": "England & Wales",
    "united kingdom": "United Kingdom", "singapore": "Singapore",
    "germany": "Germany", "france": "France", "ireland": "Ireland",
}


# ————————————————————————— parsing helpers —————————————————————————
def extract_months(text: str) -> int | None:
    """Parse a duration in months from clause text. Handles '6 months',
    'twelve (12) months', 'sixty (60) months', 'two (2) years'."""
    t = text.lower()
    m = re.search(r"\(?(\d+)\)?\s*months?", t)
    if m:
        return int(m.group(1))
    y = re.search(r"\(?(\d+)\)?\s*years?", t)
    if y:
        return int(y.group(1)) * 12
    return None


def detect_jurisdiction(text: str) -> str | None:
    t = text.lower()
    for key, name in _JURISDICTIONS.items():
        if key in t:
            return name
    return None


def _heading_of(line: str) -> tuple[str, str] | None:
    s = line.strip()
    if not s:
        return None
    m = re.match(r"^(\d+)[.)]\s+(.+)$", s)                      # "1. Foo" / "1) Foo"
    if m:
        return m.group(1), m.group(2).strip()
    m = re.match(r"^section\s+(\d+)[.:\-\s]+(.+)$", s, re.I)     # "Section 1 - Foo"
    if m:
        return m.group(1), m.group(2).strip()
    m = re.match(r"^#{1,3}\s*(?:(\d+)[.)]\s*)?(.+)$", s)          # "## 1. Foo" / "## Foo"
    if m:
        return (m.group(1) or ""), m.group(2).strip()
    return None


def segment(text: str) -> list[tuple[str, str, str]]:
    """Split pasted NDA text into (section_no, heading, body) tuples."""
    lines = text.replace("\r\n", "\n").split("\n")
    clauses: list[tuple[str, str, str]] = []
    cur_no, cur_head, cur_body = "", "", []
    started = False

    def flush():
        if started:
            clauses.append((cur_no, cur_head, "\n".join(cur_body).strip()))

    for line in lines:
        h = _heading_of(line)
        if h is not None:
            flush()
            cur_no, cur_head = h
            cur_body = []
            started = True
        elif started:
            cur_body.append(line)
    flush()

    if not clauses:  # no headings found — treat the whole thing as one clause
        clauses = [("", "Document", text.strip())]
    return clauses


def keyword_map_for(rules, include_base: bool) -> dict[str, list[str]]:
    """Derive the clause-classification keywords from a playbook's OWN rules —
    each rule contributes its heading and the meaningful words of its
    clause_type. This is what frees the redline engine from the NDA-hardcoded
    map: a DPA playbook classifies DPA paper. The NDA base map folds in only
    when asked (include_base), since NDAs predate rule-derived keywords."""
    m: dict[str, list[str]] = {k: list(v) for k, v in CLAUSE_KEYWORDS.items()} if include_base else {}
    for r in rules:
        kws = m.setdefault(r.clause_type, [])
        h = (r.heading or "").lower().strip()
        if h and h not in kws:
            kws.append(h)
        for w in (r.clause_type or "").split("_"):
            if len(w) > 4 and w not in kws:
                kws.append(w)
    return m


def classify(heading: str, body: str, kmap: dict[str, list[str]] | None = None) -> str | None:
    """Best-match clause_type by keyword hits (heading weighted higher)."""
    h, b = heading.lower(), body.lower()
    best, best_score = None, 0
    for ctype, kws in (kmap or CLAUSE_KEYWORDS).items():
        score = 0
        for kw in kws:
            if kw in h:
                score += 3
            elif kw in b:
                score += 1
        if score > best_score:
            best, best_score = ctype, score
    return best if best_score > 0 else None


# ————————————————————————— the checks —————————————————————————
def _fill(template: str, ctx: dict) -> str:
    out = template
    for k, v in ctx.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def _check_liability(body: str) -> tuple[bool, list[dict]]:
    """DETERMINISTIC only — parse the cap and compare to our floor. The
    confidentiality carve-out (a semantic judgement) is handled by the AI layer."""
    cap = extract_months(body)
    if cap is not None:
        ok = cap >= LIABILITY_CAP_FLOOR_MONTHS
        return (not ok), [{
            "kind": "DETERMINISTIC", "name": "liability_cap_floor", "passed": ok,
            "detail": f"parsed cap = {cap}mo vs floor {LIABILITY_CAP_FLOOR_MONTHS}mo",
        }]
    return True, [{
        "kind": "DETERMINISTIC", "name": "liability_cap_floor", "passed": False,
        "detail": "no numeric cap found — needs an explicit fees-based cap",
    }]


def _check_term(body: str) -> tuple[bool, list[dict]]:
    months = extract_months(body)
    if months is None:
        return False, [{
            "kind": "DETERMINISTIC", "name": "term_length", "passed": True,
            "detail": "no explicit term found",
        }]
    ok = months <= TERM_MAX_MONTHS
    return (not ok), [{
        "kind": "DETERMINISTIC", "name": "term_length", "passed": ok,
        "detail": f"parsed term = {months}mo vs max {TERM_MAX_MONTHS}mo",
    }]


def _check_governing_law(body: str) -> tuple[bool, list[dict]]:
    juris = detect_jurisdiction(body)
    if juris is None:
        return False, [{
            "kind": "DETERMINISTIC", "name": "governing_law", "passed": True,
            "detail": "no jurisdiction detected",
        }]
    ok = juris in ACCEPTABLE_JURISDICTIONS
    return (not ok), [{
        "kind": "DETERMINISTIC", "name": "governing_law", "passed": ok,
        "detail": f"detected '{juris}'"
                  + ("" if ok else f" — outside our acceptable set {sorted(ACCEPTABLE_JURISDICTIONS)}"),
    }]


_CHECKERS = {
    "limitation_of_liability": _check_liability,
    "term": _check_term,
    "governing_law": _check_governing_law,
}
_CONFIDENCE = {"limitation_of_liability": 0.86, "term": 0.95, "governing_law": 0.9}


# ————————————————————————— the run —————————————————————————
def run_inbound_review(db: Session, request: Request, ai=None) -> ReviewRun:
    from .ai import get_ai_client

    ai = ai or get_ai_client()
    doc = db.get(Document, request.document_id)
    version = db.get(DocumentVersion, doc.current_version_id)
    clauses = db.execute(
        select(Clause).where(Clause.document_version_id == version.id).order_by(Clause.ordinal.asc())
    ).scalars().all()

    # resolve the request's playbook (specific one if named, else org default) and
    # load ONLY its rules, filtered to the ones that apply to this NDA type. Before
    # this, the redline loaded every rule in the database — all playbooks, all orgs —
    # and collided them by clause_type. Stamp the resolved playbook onto the request.
    from .playbooks import load_rules, resolve_playbook, rule_applies

    tkey = (request.type or "nda").lower()
    playbook = resolve_playbook(db, request.org_id, request.playbook_id, contract_type=tkey)
    request.playbook_id = playbook.id
    rules = [r for r in load_rules(db, playbook.id) if rule_applies(r, request)]
    rule_by_type = {r.clause_type: r for r in rules}

    counterparty = db.get(Counterparty, request.counterparty_id)
    ctx = {
        "counterparty.name": counterparty.name,
        "org.name": "Northwind Technologies, Inc.",
        "matter.purpose": request.purpose.replace("_", " "),
        "hold.term_months": request.term_months,
    }

    run = ReviewRun(request_id=request.id, document_version_id=version.id)
    db.add(run)
    db.flush()

    changes: list[ProposedChange] = []
    seen_types: set[str] = set()
    ordinal = 0

    # 1) evaluate every clause the counterparty included
    for clause in clauses:
        ctype = clause.clause_type
        if ctype:
            seen_types.add(ctype)
        rule = rule_by_type.get(ctype) if ctype else None

        if rule is None:  # no playbook position -> a human should read it
            ordinal += 1
            changes.append(ProposedChange(
                run_id=run.id, ordinal=ordinal, clause_id=clause.id,
                section_no=clause.section_no, heading=clause.heading or "Unrecognised clause",
                finding="NOVEL", rule_key=None,
                before_text=clause.body_text, after_text="",
                rationale="We have no playbook position on this clause — a human should read it.",
                checks=[{"kind": "SEMANTIC", "name": "playbook_match", "passed": False,
                         "detail": "no matching playbook rule"}],
                confidence=None, triggered_rung="none",
            ))
            continue

        checks: list[dict] = []
        is_dev = False
        after = _fill(rule.preferred_body, ctx)
        conf: float | None = None

        # DETERMINISTIC layer — numbers/dates the LLM shouldn't be trusted with.
        # The liability-floor and term-ceiling constants are NDA policy; running
        # them against e.g. a DPA (whose preferred liability position is UNCAPPED)
        # would flag our own preferred language as a deviation. The governing-law
        # set is org-wide and applies to every contract type.
        checker = _CHECKERS.get(ctype) if (tkey == "nda" or ctype == "governing_law") else None
        if checker:
            det_dev, det_checks = checker(clause.body_text)
            checks += det_checks
            if det_dev:
                is_dev = True
                conf = _CONFIDENCE.get(ctype, conf)

        # SEMANTIC layer — Claude (or heuristic fallback); may abstain (None)
        verdict = ai.compare_clause(clause.body_text, rule, ctx, contract_type=tkey)
        if verdict is not None:
            checks.append({
                "kind": "SEMANTIC", "name": "position_match", "passed": verdict.matches,
                "detail": verdict.note, "model": verdict.model,
            })
            if not verdict.matches:
                is_dev = True
                if verdict.suggested_after:
                    after = verdict.suggested_after
                if conf is None:
                    conf = verdict.confidence

        if is_dev:
            # Position-ladder pass (Ivo-style): a deviation may still sit inside an
            # acceptable FALLBACK (accept their language at that fallback's approval
            # price) or cross the WALK-AWAY line (always escalates to GC).
            finding = "DEVIATION"
            rung = rule.deviation_rung
            rationale = rule.rationale or f"Outside our position on {rule.heading.lower()}."
            semantic_flagged = any(
                ch.get("kind") == "SEMANTIC" and not ch.get("passed") for ch in checks
            )
            ladder = ai.place_on_ladder(clause.body_text, rule, ctx, semantic_flagged) if (
                (rule.fallbacks or []) or (rule.walk_away_text or "").strip()
            ) else None
            if ladder is not None:
                checks.append({
                    "kind": "SEMANTIC", "name": "position_ladder",
                    "passed": ladder.position == "fallback" and ladder.fallback_index is not None,
                    "detail": f"{ladder.position}: {ladder.note}", "model": ladder.model,
                })
                if ladder.position == "fallback" and ladder.fallback_index is not None:
                    fb = (rule.fallbacks or [])[ladder.fallback_index]
                    finding = "ACCEPTABLE_FALLBACK"
                    rung = fb.get("rung") or rule.deviation_rung
                    after = clause.body_text  # accept their language at the fallback price
                    rationale = (
                        f"Their language sits within our fallback position "
                        f"'{fb.get('label', f'#{ladder.fallback_index + 1}')}' — acceptable "
                        f"with {rung.replace('_', ' ')} approval." if rung != "none" else
                        f"Their language sits within our fallback position "
                        f"'{fb.get('label', f'#{ladder.fallback_index + 1}')}' — acceptable as-is."
                    )
                elif ladder.position == "walk_away":
                    rung = "gc"
                    rationale = (
                        f"WALK-AWAY BREACH — their clause crosses the line we never accept "
                        f"({rule.walk_away_text.strip()}). Propose our preferred language; "
                        "GC sign-off required to proceed at all."
                    )
                if conf is None:
                    conf = ladder.confidence
            ordinal += 1
            changes.append(ProposedChange(
                run_id=run.id, ordinal=ordinal, clause_id=clause.id,
                section_no=clause.section_no, heading=rule.heading,
                finding=finding, rule_key=rule.rule_key,
                before_text=clause.body_text, after_text=after,
                rationale=rationale,
                checks=checks, confidence=conf, triggered_rung=rung,
            ))

    # 2) mandatory clauses the counterparty omitted entirely
    for rule in rules:
        if rule.mandatory and rule.clause_type not in seen_types:
            ordinal += 1
            changes.append(ProposedChange(
                run_id=run.id, ordinal=ordinal, clause_id=None,
                section_no="", heading=rule.heading,
                finding="MISSING", rule_key=rule.rule_key,
                before_text="", after_text=_fill(rule.preferred_body, ctx),
                rationale=f"Our standard '{rule.heading}' clause is absent — propose inserting it.",
                checks=[{"kind": "DETERMINISTIC", "name": "mandatory_presence", "passed": False,
                         "detail": f"no clause classified as {rule.clause_type}"}],
                confidence=0.9, triggered_rung=rule.deviation_rung,
            ))

    db.add_all(changes)

    summary = {"deviation": 0, "missing": 0, "novel": 0, "acceptable_fallback": 0, "compliant": 0}
    for c in changes:
        key = c.finding.lower()
        summary[key] = summary.get(key, 0) + 1
    # compliant = clause types we actually reviewed against a rule and cleared;
    # rule-less (NOVEL) types are unreviewed, not compliant
    reviewed_types = seen_types & set(rule_by_type.keys())
    summary["compliant"] = max(
        0, len(reviewed_types) - summary["deviation"] - summary.get("acceptable_fallback", 0)
    )
    run.summary = summary
    db.flush()
    return run


def latest_run(db: Session, request_id: str) -> ReviewRun | None:
    return db.execute(
        select(ReviewRun)
        .where(ReviewRun.request_id == request_id)
        .order_by(ReviewRun.created_at.desc())
    ).scalars().first()


def required_rungs(run: ReviewRun) -> list[str]:
    """Distinct approval rungs the deviations trigger (the ladder, informational)."""
    order = {"requesting_manager": 0, "vp_legal": 1, "gc": 2}
    rungs = {c.triggered_rung for c in run.changes if c.triggered_rung and c.triggered_rung != "none"}
    return sorted(rungs, key=lambda r: order.get(r, 9))


def build_counter_markdown(db: Session, request: Request, run: ReviewRun) -> str:
    """Preview of what we'd send back: the counterparty's clauses with our
    APPROVED edits applied, rejected edits leaving their language, and approved
    MISSING clauses appended."""
    doc = db.get(Document, request.document_id)
    version = db.get(DocumentVersion, doc.current_version_id)
    clauses = db.execute(
        select(Clause).where(Clause.document_version_id == version.id).order_by(Clause.ordinal.asc())
    ).scalars().all()

    change_by_clause = {c.clause_id: c for c in run.changes if c.clause_id}
    lines: list[str] = [f"# Counter-proposal — {db.get(Counterparty, request.counterparty_id).name} NDA", ""]
    n = 0
    for clause in clauses:
        n += 1
        change = change_by_clause.get(clause.id)
        heading = clause.heading or (change.heading if change else "Clause")
        lines.append(f"## {n}. {heading}")
        lines.append("")
        # apply the approved redline when it actually changes their language —
        # covers DEVIATIONs and any approve-with-edit on fallback/novel findings
        # (a lawyer's vetted edit must never be silently dropped from the counter)
        applies = (
            change is not None
            and change.decision.startswith("APPROVED")
            and change.after_text.strip()
            and change.after_text.strip() != clause.body_text.strip()
            and (change.finding == "DEVIATION" or change.decision == "APPROVED_WITH_EDIT")
        )
        if applies:
            lines.append(f"~~{clause.body_text}~~")
            lines.append("")
            lines.append(f"**{change.after_text}**")
            lines.append("_(our redline — accepted)_")
        else:
            lines.append(clause.body_text)
        lines.append("")

    for change in run.changes:
        if change.finding == "MISSING" and change.decision.startswith("APPROVED"):
            n += 1
            lines.append(f"## {n}. {change.heading}")
            lines.append("")
            lines.append(f"**{change.after_text}**")
            lines.append("_(added — was missing from their paper)_")
            lines.append("")
    return "\n".join(lines)
