"""E-signature — stubbed.

Real integration (DocuSign / Adobe) is a swap at this seam: ``send_for_signature``
would create an envelope and return its id; a provider webhook would later flip
the request to EXECUTED. For the skeleton, ``send_for_signature`` records the
envelope and ``simulate_signature`` stands in for the counterparty signing, so
the demo walks the whole way to FILED without a provider account.
"""
from __future__ import annotations

import uuid


def send_for_signature(document_title: str, recipient: str) -> dict:
    return {
        "envelope_id": "env_" + uuid.uuid4().hex[:16],
        "provider": "stub",
        "recipient": recipient,
        "status": "sent",
    }
