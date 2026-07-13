"""Seed reference data: one org, the legal reviewers, a couple of counterparties,
and a full NDA playbook (the pre-approved clause library the outbound generator
assembles from).

Idempotent: if an organisation already exists it exits without touching data.
Run ``python -m app.seed`` from the backend directory.
"""
from __future__ import annotations

from sqlalchemy import select

from .config import settings
from .db import Base, SessionLocal, engine
from .models import Counterparty, Organization, Person, Playbook, PlaybookRule, User
from .security import hash_password


def _rule(pb_id, key, ordinal, clause_type, heading, position, body, rung="none", rationale="", mandatory=True):
    return PlaybookRule(
        playbook_id=pb_id,
        rule_key=key,
        clause_type=clause_type,
        heading=heading,
        ordinal=ordinal,
        applies_when={},
        preferred_position=position,
        preferred_body=body,
        structured_params={},
        mandatory=mandatory,
        deviation_rung=rung,
        rationale=rationale,
    )


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.execute(select(Organization)).scalars().first():
            print("• already seeded — skipping (drop tables to reseed)")
            return

        org = Organization(name="Northwind Technologies, Inc.")
        db.add(org)
        db.flush()

        pw = hash_password(settings.auth_demo_password)
        db.add_all(
            [
                User(org_id=org.id, name="Dana Osei", email="dana.osei@northwind.example", role="vp_legal", password_hash=pw),
                User(org_id=org.id, name="Priya Nair", email="priya.nair@northwind.example", role="gc", password_hash=pw),
                User(org_id=org.id, name="Marcus Reid", email="marcus.reid@northwind.example", role="attorney", password_hash=pw),
                User(org_id=org.id, name="Sam Carter", email="sam.carter@northwind.example", role="requester", password_hash=pw),
                User(org_id=org.id, name="Val Ng", email="val.ng@northwind.example", role="viewer", password_hash=pw),
                User(org_id=org.id, name="Admin", email="admin@northwind.example", role="admin", password_hash=pw),
            ]
        )

        db.add_all(
            [
                Counterparty(org_id=org.id, name="Acme Corporation", domain="acme.example"),
                Counterparty(org_id=org.id, name="Globex LLC", domain="globex.example"),
                Counterparty(org_id=org.id, name="Sanctioned Entity Ltd", sanctioned=True),
            ]
        )

        db.add(
            Person(
                org_id=org.id, name="Sam Carter", email="sam.carter@northwind.example",
                department="Sales",
            )
        )

        playbook = Playbook(org_id=org.id, name="Northwind Standard NDA", version=1, active=True)
        db.add(playbook)
        db.flush()

        rules = [
            _rule(
                playbook.id, "DEF-01", 1, "confidential_information_definition",
                "Definition of Confidential Information",
                "Broad definition; marked or reasonably-understood-confidential information both covered.",
                "“Confidential Information” means all non-public information disclosed by one party "
                "(the “Disclosing Party”) to the other (the “Receiving Party”) in connection with "
                "{{matter.purpose}}, whether disclosed orally, in writing, or by inspection of "
                "tangible objects, that is designated as confidential or that reasonably should be "
                "understood to be confidential given its nature and the circumstances of disclosure.",
                rationale="A broad definition protects Northwind's disclosures.",
            ),
            _rule(
                playbook.id, "PUR-01", 2, "purpose", "Purpose",
                "Confidential Information used solely for the stated purpose.",
                "The Receiving Party shall use the Confidential Information solely for the purpose of "
                "{{matter.purpose}} (the “Purpose”) and for no other purpose without the Disclosing "
                "Party's prior written consent.",
            ),
            _rule(
                playbook.id, "OBL-01", 3, "confidentiality_obligations", "Obligations of Confidentiality",
                "Reasonable care, at least the degree used for own confidential information.",
                "The Receiving Party shall (a) hold the Confidential Information in strict confidence; "
                "(b) not disclose it to any third party except to employees and advisors with a need "
                "to know who are bound by confidentiality obligations no less protective than these; "
                "and (c) protect it using at least the degree of care it uses for its own confidential "
                "information of like importance, and in no event less than a reasonable degree of care.",
            ),
            _rule(
                playbook.id, "EXC-01", 4, "exclusions", "Exclusions",
                "Standard four carve-outs (public, prior possession, independently developed, rightfully received).",
                "Confidential Information does not include information that: (a) is or becomes publicly "
                "available through no breach of this Agreement; (b) was rightfully in the Receiving "
                "Party's possession without restriction before disclosure; (c) is independently "
                "developed without use of the Confidential Information; or (d) is rightfully received "
                "from a third party without a duty of confidentiality.",
            ),
            _rule(
                playbook.id, "TRM-01", 5, "term", "Term and Survival",
                "Confidentiality obligations survive {{hold.term_months}} months from disclosure.",
                "This Agreement commences on the Effective Date and continues for {{hold.term_months}} "
                "months, provided that the Receiving Party's confidentiality obligations with respect "
                "to Confidential Information disclosed during the term shall survive for {{hold.term_months}} "
                "months following disclosure.",
                rung="vp_legal",
                rationale="Term deviations change our exposure window; VP Legal owns the sign-off.",
            ),
            _rule(
                playbook.id, "RET-01", 6, "return_destruction", "Return or Destruction",
                "On request, return or destroy and certify within 30 days.",
                "Upon the Disclosing Party's written request or termination of this Agreement, the "
                "Receiving Party shall promptly return or destroy all Confidential Information and, "
                "upon request, certify such destruction in writing within thirty (30) days.",
            ),
            _rule(
                playbook.id, "LIC-01", 7, "no_license", "No License; No Warranty",
                "No license granted; information provided as-is.",
                "No license or other right to any intellectual property is granted under this Agreement. "
                "All Confidential Information is provided “as is” without warranty of any kind.",
            ),
            _rule(
                playbook.id, "INJ-01", 8, "injunctive_relief", "Injunctive Relief",
                "Equitable relief available for breach.",
                "The parties agree that a breach of this Agreement may cause irreparable harm for which "
                "monetary damages are an inadequate remedy, and that the Disclosing Party is entitled "
                "to seek injunctive relief in addition to any other remedies at law or in equity.",
            ),
            _rule(
                playbook.id, "GOV-01", 9, "governing_law", "Governing Law and Jurisdiction",
                "Governed by Delaware law; Northwind's home jurisdiction preferred.",
                "This Agreement is governed by the laws of the State of Delaware, without regard to its "
                "conflict-of-laws principles, and the parties consent to the exclusive jurisdiction of "
                "the state and federal courts located in Delaware.",
                rung="gc",
                rationale="Governing-law changes affect enforceability; the GC signs off on deviations.",
            ),
            _rule(
                playbook.id, "LoL-02", 10, "limitation_of_liability", "Limitation of Liability",
                "Cap at 12 months' fees; confidentiality breach always carved out.",
                "Except for breaches of confidentiality obligations, neither party's aggregate liability "
                "arising out of this Agreement shall exceed the fees paid or payable in the twelve (12) "
                "months preceding the claim. Nothing in this Section limits liability for breach of the "
                "confidentiality obligations herein.",
                rung="vp_legal",
                rationale="Liability caps and the confidentiality carve-out are non-negotiable positions.",
            ),
            _rule(
                playbook.id, "ASG-01", 11, "assignment", "No Assignment",
                "No assignment without consent.",
                "Neither party may assign this Agreement without the other party's prior written consent, "
                "except to a successor in connection with a merger or sale of substantially all assets.",
            ),
            _rule(
                playbook.id, "GEN-01", 12, "entire_agreement", "Entire Agreement; Notices",
                "Entire agreement; written amendments; notice terms.",
                "This Agreement is the entire agreement between the parties regarding its subject matter "
                "and supersedes all prior understandings. It may be amended only in a writing signed by "
                "both parties. Notices must be in writing and sent to the parties' designated contacts.",
            ),
        ]
        db.add_all(rules)
        db.commit()
        print(f"• seeded org '{org.name}', 6 users, 3 counterparties, playbook with {len(rules)} rules")
        print(f"• logins (password '{settings.auth_demo_password}'): admin@ / priya.nair@ (gc) / "
              f"dana.osei@ (vp_legal) / marcus.reid@ (attorney) / sam.carter@ (requester) / val.ng@ (viewer) "
              f"— all @northwind.example")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
