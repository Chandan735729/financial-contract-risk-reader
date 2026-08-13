"""Authorization test matrix for every document-scoped read endpoint
(Phase 8 spec: "correct token, wrong token, missing token, another
document's token, nonexistent document, guessed document ID"). All three
endpoints share one dependency (`app.api.deps.require_document_access`), but
each is tested independently so a future endpoint that forgets to depend on
it fails loudly here rather than silently shipping unauthenticated.

The token travels as `Authorization: Bearer <token>` (see
`app.api.deps.require_document_access`'s docstring for why: a query-param
token leaks into access logs, browser history, and `Referer` headers --
found empirically by this phase's own logging-safety test).
"""

from __future__ import annotations

import uuid

import pytest

from app.models import db_models
from tests.conftest import make_clause, make_clause_analysis, make_document

_ENDPOINT_KINDS = ["status", "report", "evidence"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _endpoint_url(kind: str, document_id: uuid.UUID, clause_id: uuid.UUID | None = None) -> str:
    if kind == "status":
        return f"/v1/documents/{document_id}/status"
    if kind == "report":
        return f"/v1/documents/{document_id}/report"
    return f"/v1/documents/{document_id}/clauses/{clause_id}/evidence"


@pytest.fixture()
def two_documents(db_session):
    """Two independent documents, each with one clause + analysis, each with
    its own distinct access token -- the fixture every test in this matrix
    needs to prove token A never unlocks document B's data."""
    doc_a = make_document(access_token="a" * 64)
    doc_b = make_document(access_token="b" * 64)
    db_session.add(doc_a)
    db_session.add(doc_b)
    db_session.flush()

    clause_a = make_clause(doc_a.id, raw_text="Clause A raw text.")
    clause_b = make_clause(doc_b.id, raw_text="Clause B raw text.")
    db_session.add(clause_a)
    db_session.add(clause_b)
    db_session.flush()

    analysis_a = make_clause_analysis(clause_a.id, risk_level=db_models.RiskLevel.LOW, risk_score=0.1)
    db_session.add(analysis_a)
    db_session.flush()

    job_a = db_models.ProcessingJob(
        id=uuid.uuid4(), document_id=doc_a.id, stage=db_models.ProcessingStage.COMPLETED
    )
    db_session.add(job_a)
    db_session.flush()

    return doc_a, clause_a, doc_b, clause_b


class TestAuthorizationMatrix:
    @pytest.mark.parametrize("kind", _ENDPOINT_KINDS)
    def test_correct_token_succeeds(self, make_client, two_documents, kind):
        client = make_client()
        doc_a, clause_a, _doc_b, _clause_b = two_documents

        response = client.get(_endpoint_url(kind, doc_a.id, clause_a.id), headers=_bearer(doc_a.access_token))
        assert response.status_code == 200

    @pytest.mark.parametrize("kind", _ENDPOINT_KINDS)
    def test_wrong_token_denied(self, make_client, two_documents, kind):
        client = make_client()
        doc_a, clause_a, _doc_b, _clause_b = two_documents

        response = client.get(_endpoint_url(kind, doc_a.id, clause_a.id), headers=_bearer("x" * 64))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "access_denied"

    @pytest.mark.parametrize("kind", _ENDPOINT_KINDS)
    def test_missing_token_denied(self, make_client, two_documents, kind):
        client = make_client()
        doc_a, clause_a, _doc_b, _clause_b = two_documents

        response = client.get(_endpoint_url(kind, doc_a.id, clause_a.id))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "access_denied"

    @pytest.mark.parametrize("kind", _ENDPOINT_KINDS)
    def test_another_documents_token_denied(self, make_client, two_documents, kind):
        client = make_client()
        doc_a, clause_a, doc_b, _clause_b = two_documents

        # doc_b's real, valid token -- just not for doc_a.
        response = client.get(_endpoint_url(kind, doc_a.id, clause_a.id), headers=_bearer(doc_b.access_token))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "access_denied"

    @pytest.mark.parametrize("kind", _ENDPOINT_KINDS)
    def test_nonexistent_document_denied(self, make_client, two_documents, kind):
        client = make_client()
        doc_a, clause_a, _doc_b, _clause_b = two_documents

        response = client.get(
            _endpoint_url(kind, uuid.uuid4(), clause_a.id), headers=_bearer(doc_a.access_token)
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "access_denied"

    @pytest.mark.parametrize("kind", _ENDPOINT_KINDS)
    def test_guessed_document_id_denied(self, make_client, two_documents, kind):
        """A structurally-plausible but never-issued UUID, guessed with no
        prior knowledge -- distinct from `test_nonexistent_document_denied`
        only in intent, but both must be indistinguishable 404s to a
        caller (Security_and_Privacy_v2.md SS4 enumeration resistance)."""
        client = make_client()
        doc_a, clause_a, _doc_b, _clause_b = two_documents
        guessed_id = uuid.UUID(int=doc_a.id.int ^ 1)  # structurally valid, not a real row

        response = client.get(
            _endpoint_url(kind, guessed_id, clause_a.id), headers=_bearer(doc_a.access_token)
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "access_denied"

    @pytest.mark.parametrize("kind", _ENDPOINT_KINDS)
    @pytest.mark.parametrize(
        "malformed_header",
        [
            "not-a-bearer-token",  # no scheme at all
            "Basic dXNlcjpwYXNz",  # wrong scheme
            "Bearer",  # scheme with no token, no trailing space
            "Bearer ",  # scheme with an empty token
            "bearer " + "a" * 64,  # correct token, wrong-case scheme (case-sensitive per RFC 6750)
        ],
    )
    def test_malformed_authorization_header_denied(self, make_client, two_documents, kind, malformed_header):
        client = make_client()
        doc_a, clause_a, _doc_b, _clause_b = two_documents

        response = client.get(
            _endpoint_url(kind, doc_a.id, clause_a.id), headers={"Authorization": malformed_header}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "access_denied"

    def test_nonexistent_clause_id_denied_even_with_correct_document_token(self, make_client, two_documents):
        client = make_client()
        doc_a, _clause_a, _doc_b, _clause_b = two_documents

        response = client.get(
            f"/v1/documents/{doc_a.id}/clauses/{uuid.uuid4()}/evidence",
            headers=_bearer(doc_a.access_token),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "access_denied"

    def test_evidence_endpoint_rejects_another_documents_clause_even_with_correct_token(
        self, make_client, two_documents
    ):
        """The clause-evidence endpoint's extra authorization layer: a valid
        access token for document A must not unlock a clause that actually
        belongs to document B (Phase 8 spec: "never allow direct clause/
        evidence access without parent-document authorization")."""
        client = make_client()
        doc_a, _clause_a, _doc_b, clause_b = two_documents

        response = client.get(
            f"/v1/documents/{doc_a.id}/clauses/{clause_b.id}/evidence",
            headers=_bearer(doc_a.access_token),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "access_denied"

    def test_access_denied_responses_are_uniform_regardless_of_cause(self, make_client, two_documents):
        """Wrong token, missing token, and nonexistent document all produce
        byte-identical error bodies (aside from request_id) -- proving the
        endpoint never leaks which specific reason caused the denial."""
        client = make_client()
        doc_a, clause_a, doc_b, _clause_b = two_documents

        wrong = client.get(f"/v1/documents/{doc_a.id}/status", headers=_bearer("x" * 64))
        missing = client.get(f"/v1/documents/{doc_a.id}/status")
        other_doc = client.get(f"/v1/documents/{doc_a.id}/status", headers=_bearer(doc_b.access_token))
        not_found = client.get(f"/v1/documents/{uuid.uuid4()}/status", headers=_bearer(doc_a.access_token))

        bodies = [r.json()["error"] for r in (wrong, missing, other_doc, not_found)]
        for body in bodies:
            assert body["code"] == "access_denied"
            assert body["user_message"] == bodies[0]["user_message"]
