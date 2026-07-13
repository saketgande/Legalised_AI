"""E-signature — provider abstraction.

`get_esign_client()` returns the DocuSign client when DocuSign env vars are set,
else the stub (so the demo signs end-to-end with no account). Both implement the
same `send_for_signature` seam; the webhook (routers/esign.py) flips the request
to EXECUTED when the provider reports completion.
"""
from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass

import httpx

from ..config import settings


@dataclass
class EnvelopeResult:
    envelope_id: str
    provider: str
    status: str  # sent | completed | declined


def render_document_html(title: str, body_markdown: str) -> str:
    """Minimal HTML rendering of the NDA for the signing packet. The `/sig/`
    anchor is where the provider drops the signature tab."""
    lines: list[str] = []
    for line in body_markdown.split("\n"):
        s = line.rstrip()
        if s.startswith("## "):
            lines.append(f"<h2>{s[3:]}</h2>")
        elif s.startswith("# "):
            lines.append(f"<h1>{s[2:]}</h1>")
        elif s.strip() == "---":
            lines.append("<hr/>")
        elif s.strip():
            lines.append(f"<p>{s}</p>")
    body = "\n".join(lines)
    return (
        f"<html><head><meta charset='utf-8'><title>{title}</title></head><body>"
        f"{body}"
        "<p style='margin-top:48px'>Signature: <span>/sig/</span></p>"
        "</body></html>"
    )


class StubEsignClient:
    provider = "stub"

    def send_for_signature(self, *, subject: str, document_html: str,
                           signer_email: str, signer_name: str) -> EnvelopeResult:
        return EnvelopeResult(f"env_{uuid.uuid4().hex[:16]}", self.provider, "sent")


class DocuSignError(RuntimeError):
    pass


class DocuSignClient:
    """Creates a DocuSign envelope via the eSignature REST API. Auth is a bearer
    access token (dev). Production would use JWT grant to mint tokens; the send
    seam is identical, so that swap doesn't touch callers."""
    provider = "docusign"

    def __init__(self, base_uri: str, account_id: str, access_token: str):
        self.base_uri = base_uri.rstrip("/")
        self.account_id = account_id
        self.access_token = access_token

    def send_for_signature(self, *, subject: str, document_html: str,
                           signer_email: str, signer_name: str) -> EnvelopeResult:
        envelope = {
            "emailSubject": subject,
            "documents": [{
                "documentBase64": base64.b64encode(document_html.encode("utf-8")).decode(),
                "name": subject, "fileExtension": "html", "documentId": "1",
            }],
            "recipients": {"signers": [{
                "email": signer_email, "name": signer_name, "recipientId": "1", "routingOrder": "1",
                "tabs": {"signHereTabs": [{"anchorString": "/sig/", "anchorUnits": "pixels",
                                           "anchorXOffset": "20", "anchorYOffset": "-5"}]},
            }]},
            "status": "sent",
        }
        try:
            resp = httpx.post(
                f"{self.base_uri}/v2.1/accounts/{self.account_id}/envelopes",
                headers={"Authorization": f"Bearer {self.access_token}", "content-type": "application/json"},
                json=envelope, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise DocuSignError(f"DocuSign rejected the envelope: {e.response.status_code}") from e
        except Exception as e:  # network etc.
            raise DocuSignError(f"DocuSign request failed: {e}") from e
        return EnvelopeResult(data.get("envelopeId", ""), self.provider, data.get("status", "sent"))


def get_esign_client():
    if settings.docusign_configured:
        return DocuSignClient(settings.docusign_base_uri, settings.docusign_account_id, settings.docusign_access_token)
    return StubEsignClient()
