"""Tests for the e-signature provider abstraction + webhook HMAC verification."""
import base64
import hashlib
import hmac

import pytest

from app.routers.esign import _verify_hmac
from app.services import esign


def test_render_html_has_signature_anchor_and_clauses():
    html = esign.render_document_html("Mutual NDA", "## 1. Term\nLasts 12 months.")
    assert "/sig/" in html and "<h2>1. Term</h2>" in html and "Lasts 12 months." in html


def test_stub_client_returns_envelope():
    r = esign.StubEsignClient().send_for_signature(
        subject="NDA", document_html="<html>/sig/</html>", signer_email="a@b.com", signer_name="A")
    assert r.provider == "stub" and r.status == "sent" and r.envelope_id.startswith("env_")


def test_factory_defaults_to_stub(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "docusign_base_uri", "")
    assert isinstance(esign.get_esign_client(), esign.StubEsignClient)


def test_factory_uses_docusign_when_configured(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "docusign_base_uri", "https://demo.docusign.net/restapi")
    monkeypatch.setattr(config.settings, "docusign_account_id", "acct")
    monkeypatch.setattr(config.settings, "docusign_access_token", "tok")
    assert isinstance(esign.get_esign_client(), esign.DocuSignClient)


def test_docusign_send_parses_envelope(monkeypatch):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"envelopeId": "abc-123", "status": "sent"}

    monkeypatch.setattr(esign.httpx, "post", lambda *a, **k: FakeResp())
    client = esign.DocuSignClient("https://demo.docusign.net/restapi", "acct", "tok")
    r = client.send_for_signature(subject="NDA", document_html="<html>/sig/</html>",
                                  signer_email="a@b.com", signer_name="A")
    assert r.provider == "docusign" and r.envelope_id == "abc-123"


def test_docusign_send_raises_on_network(monkeypatch):
    def boom(*a, **k): raise RuntimeError("down")
    monkeypatch.setattr(esign.httpx, "post", boom)
    client = esign.DocuSignClient("https://x", "acct", "tok")
    with pytest.raises(esign.DocuSignError):
        client.send_for_signature(subject="NDA", document_html="x", signer_email="a@b.com", signer_name="A")


def test_webhook_hmac(monkeypatch):
    from app import config
    body = b'{"envelopeId":"x"}'
    # no key -> accept
    monkeypatch.setattr(config.settings, "docusign_connect_hmac", "")
    assert _verify_hmac(body, None) is True
    # key set -> require correct signature
    monkeypatch.setattr(config.settings, "docusign_connect_hmac", "secret")
    good = base64.b64encode(hmac.new(b"secret", body, hashlib.sha256).digest()).decode()
    assert _verify_hmac(body, good) is True
    assert _verify_hmac(body, "wrong") is False
    assert _verify_hmac(body, None) is False
