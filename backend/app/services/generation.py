"""Outbound NDA generation — assemble, don't free-generate.

The lowest-hallucination-risk way to draft: take the playbook's *preferred*
clauses (known-good, pre-approved language), fill the variables, and stitch
them into a document. The result is on-playbook by construction, which is why
the AUTO path can send it with no lawyer.

If ``ANTHROPIC_API_KEY`` is set we let Claude lightly polish the recitals only
(never the operative clauses) — but the deterministic assembly is the source of
truth and the product runs fully without any key.
"""
from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from ..models import (
    Clause,
    Counterparty,
    Document,
    DocumentVersion,
    NdaType,
    Person,
    Request,
)
from .playbooks import load_rules, resolve_playbook, rule_applies


def _fill(template: str, ctx: dict) -> str:
    out = template
    for key, val in ctx.items():
        out = out.replace("{{" + key + "}}", str(val))
    return out


def generate_outbound_nda(db: Session, request: Request) -> Document:
    org_id = request.org_id
    counterparty = db.get(Counterparty, request.counterparty_id)
    requester = db.get(Person, request.requester_id)

    # resolve the request's playbook (specific one if named, else org default),
    # then stamp it onto the request so the audit trail records which standard
    # produced this draft
    playbook = resolve_playbook(db, org_id, request.playbook_id)
    request.playbook_id = playbook.id
    rules = load_rules(db, playbook.id)

    ctx = {
        "counterparty.name": counterparty.name,
        "org.name": "Northwind Technologies, Inc.",
        "matter.purpose": request.purpose.replace("_", " "),
        "hold.term_months": request.term_months,
        "nda.type": "Mutual" if request.nda_type == NdaType.MUTUAL else "One-Way",
        "jurisdiction": request.jurisdiction,
    }

    title = f"{ctx['nda.type']} Non-Disclosure Agreement — {counterparty.name}"

    document = Document(org_id=org_id, request_id=request.id, origin="GENERATED", title=title)
    db.add(document)
    db.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        body_markdown="",  # filled below
        content_hash="",   # filled below
        generated_by="playbook-assembly",
    )
    db.add(version)
    db.flush()

    lines: list[str] = [
        f"# {title}",
        "",
        f"This {ctx['nda.type']} Non-Disclosure Agreement (the “Agreement”) is entered into "
        f"by and between **{ctx['org.name']}** and **{counterparty.name}** for the purpose of "
        f"{ctx['matter.purpose']}.",
        "",
    ]

    section_no = 0
    applicable = [r for r in rules if rule_applies(r, request)]
    for rule in applicable:
        section_no += 1
        body = _fill(rule.preferred_body, ctx)
        lines.append(f"## {section_no}. {rule.heading}")
        lines.append("")
        lines.append(body)
        lines.append("")
        db.add(
            Clause(
                document_version_id=version.id,
                ordinal=section_no,
                section_no=str(section_no),
                clause_type=rule.clause_type,
                heading=rule.heading,
                body_text=body,
                source_rule_key=rule.rule_key,
            )
        )

    lines.append("---")
    lines.append(
        f"_Assembled from playbook “{playbook.name}” v{playbook.version} "
        f"({len(applicable)} clauses). Requested by {requester.name}._"
    )

    body_markdown = "\n".join(lines)
    version.body_markdown = body_markdown
    version.content_hash = hashlib.sha256(body_markdown.encode("utf-8")).hexdigest()

    document.current_version_id = version.id
    request.document_id = document.id
    db.flush()
    return document
