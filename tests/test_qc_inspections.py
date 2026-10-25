from __future__ import annotations

import importlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import OperationEvent, QualityDecision, ReworkOrder, RouteStep, Shift, TrackedEntity, User, WorkSession
from app.services import canonical_payload_hash

main_module = importlib.import_module("app.main")


def _auth(client: TestClient, login, username: str) -> dict[str, str]:
    return {"X-CSRF-Token": login(client, username)["csrf_token"]}


def _session(client: TestClient) -> dict:
    response = client.get("/api/v1/work-sessions")
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["ended_at"] is None)


def _scan(client: TestClient, login, username: str, qr: str, attempt_type="PRIMARY", attempt_no=1) -> dict:
    headers = _auth(client, login, username)
    session = _session(client)
    response = client.post("/api/v1/operation-events", headers=headers, json={
        "event_id": str(uuid4()), "work_session_id": session["id"], "subject_qr": qr,
        "event_type": "COMPLETE", "attempt_type": attempt_type, "attempt_no": attempt_no,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _prepare(client: TestClient, login, qr="DEMO-WIP-004", assembly="assembly1") -> None:
    _scan(client, login, "solder", qr)
    _scan(client, login, assembly, qr)


def _body(session_id: str, inspection_id: str | None = None, qr="DEMO-WIP-004", decision="ACCEPT", defect_code=None) -> dict:
    return {
        "inspection_id": inspection_id or str(uuid4()), "work_session_id": session_id,
        "subject_qr": qr, "decision": decision, "defect_code": defect_code,
        "occurred_at_device": None,
    }


def test_qc_atomic_idempotency_actor_status_summary_and_catalog(client: TestClient, seeded_db: Session, login) -> None:
    _prepare(client, login)
    headers = _auth(client, login, "qc")
    session = _session(client)
    inspection_id = str(uuid4())
    missing = client.get(f"/api/v1/qc-inspections/{inspection_id}/status").json()
    assert missing["status"] == "NOT_FOUND" and missing["terminal"] is False
    body = _body(session["id"], inspection_id, decision="REJECT", defect_code="DEMO-ASSEMBLY")
    created = client.post("/api/v1/qc-inspections", headers=headers, json=body)
    assert created.status_code == 200, created.text
    assert created.json()["inspection"]["mode"] == "FIRST_PASS"
    assert created.json()["inspection"]["defect_label"] == "ДЕМО · сборка"
    retry = client.post("/api/v1/qc-inspections", headers=headers, json=body)
    assert retry.status_code == 200 and retry.json()["duplicate"] is True
    changed = client.post("/api/v1/qc-inspections", headers=headers, json={**body, "decision": "ACCEPT", "defect_code": None})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "QC_INSPECTION_PAYLOAD_MISMATCH"
    assert changed.json()["submission"]["terminal"] is False
    status = client.get(f"/api/v1/qc-inspections/{inspection_id}/status")
    assert status.json()["inspection"]["decision"] == "REJECT"
    _auth(client, login, "admin")
    assert client.get(f"/api/v1/qc-inspections/{inspection_id}/status").status_code == 403
    foreign = client.post(
        "/api/v1/qc-inspections",
        headers={"X-CSRF-Token": client.get("/api/v1/auth/me").json()["user"]["csrf_token"]}, json=body,
    )
    assert foreign.status_code == 403 and foreign.json()["submission"]["terminal"] is False
    _auth(client, login, "qc")
    summary = client.get("/api/v1/me/qc-shift-activity").json()
    assert (summary["checked_count"], summary["accepted_count"], summary["rejected_count"]) == (4, 2, 2)
    assert summary["first_pass_count"] == 4 and summary["reinspection_count"] == 0
    assert summary["recent_inspections"][0]["inspection_id"] == inspection_id
    catalog = client.get("/api/v1/qc-defect-reasons").json()
    assert catalog["synthetic"] is True
    assert {item["code"] for item in catalog["items"]} == {"DEMO-JOINT", "DEMO-ASSEMBLY", "DEMO-COMPONENT", "DEMO-OTHER"}
    assert seeded_db.scalar(select(func.count()).select_from(QualityDecision).where(QualityDecision.request_id == inspection_id)) == 1
    replay = main_module._qc_replay_after_conflict(
        seeded_db,
        inspection_id,
        seeded_db.scalar(select(User.id).where(User.username == "qc")),
        canonical_payload_hash(body),
    )
    assert replay is not None and replay["duplicate"] is True

    saved_event = seeded_db.get(OperationEvent, created.json()["inspection"]["event_id"])
    admin_id = seeded_db.scalar(select(User.id).where(User.username == "admin"))
    seeded_db.add(OperationEvent(
        id=str(uuid4()), payload_hash="a" * 64, shift_id=saved_event.shift_id,
        work_session_id=saved_event.work_session_id, entity_id=saved_event.entity_id,
        route_step_id=saved_event.route_step_id, plan_line_id=saved_event.plan_line_id,
        user_id=admin_id, attempt_no=saved_event.attempt_no, attempt_type=saved_event.attempt_type,
        event_type="CORRECTION", outcome="CANCELLED", status="ACCEPTED",
        code="DEMO_CORRECTION", correction_of_id=saved_event.id,
    ))
    seeded_db.commit()
    corrected_summary = client.get("/api/v1/me/qc-shift-activity").json()
    assert corrected_summary["checked_count"] == 3
    corrected_item = next(item for item in corrected_summary["recent_inspections"] if item["inspection_id"] == inspection_id)
    assert corrected_item["corrected"] is True
    assert corrected_item["display_status"] == "CORRECTED"


def test_invalid_reason_and_wrong_route_are_terminal_without_rows(client: TestClient, seeded_db: Session, login) -> None:
    headers = _auth(client, login, "qc")
    session = _session(client)
    bodies = [
        _body(session["id"], decision="REJECT"),
        _body(session["id"], decision="REJECT", defect_code="UNKNOWN"),
        _body(session["id"], decision="ACCEPT", defect_code="DEMO-OTHER"),
        _body(session["id"], qr="DEMO-WIP-008"),
    ]
    for body in bodies:
        response = client.post("/api/v1/qc-inspections", headers=headers, json=body)
        assert response.status_code in {409, 422}
        assert response.json()["submission"]["inspection_id"] == body["inspection_id"]
        assert response.json()["submission"]["terminal"] is True
        assert seeded_db.get(OperationEvent, body["inspection_id"]) is None
        assert seeded_db.scalar(select(QualityDecision).where(QualityDecision.request_id == body["inspection_id"])) is None
    assert response.json()["error"]["code"] == "ROUTE_VIOLATION"


def test_qc_reuses_exact_legacy_unpaired_completion(client: TestClient, seeded_db: Session, login) -> None:
    _prepare(client, login)
    legacy = _scan(client, login, "qc", "DEMO-WIP-004")
    headers = {"X-CSRF-Token": client.get("/api/v1/auth/me").json()["user"]["csrf_token"]}
    body = _body(_session(client)["id"])
    response = client.post("/api/v1/qc-inspections", headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["inspection"]["event_id"] == legacy["id"]
    assert response.json()["inspection"]["event_id"] != body["inspection_id"]
    assert client.post("/api/v1/qc-inspections", headers=headers, json=body).json()["duplicate"] is True
    assert seeded_db.get(OperationEvent, body["inspection_id"]) is None


def test_primary_qc_accepts_arbitrary_step_code_without_rework_permission(client: TestClient, seeded_db: Session, login) -> None:
    step = seeded_db.scalar(select(RouteStep).where(RouteStep.code == "DEMO-QC"))
    assert step
    step.code = "CFG-ARBITRARY-CONTROL"
    step.allows_rework = False
    seeded_db.commit()
    _prepare(client, login)
    headers = _auth(client, login, "qc")
    response = client.post("/api/v1/qc-inspections", headers=headers, json=_body(_session(client)["id"]))
    assert response.status_code == 200, response.text
    assert response.json()["inspection"]["route_step"]["code"] == "CFG-ARBITRARY-CONTROL"
    assert response.json()["inspection"]["mode"] == "FIRST_PASS"


def test_qc_partial_failure_rolls_back_event_decision_and_projection(client: TestClient, seeded_db: Session, login, monkeypatch) -> None:
    _prepare(client, login)
    headers = _auth(client, login, "qc")
    body = _body(_session(client)["id"])
    monkeypatch.setattr(main_module, "record_audit", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("forced audit failure")))
    with pytest.raises(RuntimeError, match="forced audit failure"):
        client.post("/api/v1/qc-inspections", headers=headers, json=body)
    seeded_db.expire_all()
    assert seeded_db.get(OperationEvent, body["inspection_id"]) is None
    assert seeded_db.scalar(select(QualityDecision).where(QualityDecision.request_id == body["inspection_id"])) is None


def test_qc_reinspection_mode_and_explicit_next_rework(client: TestClient, seeded_db: Session, login) -> None:
    rejected = seeded_db.scalar(select(QualityDecision).where(QualityDecision.decision == "REJECT"))
    assembly_step = seeded_db.scalar(select(RouteStep).where(RouteStep.code == "DEMO-ASSEMBLE"))
    foreman = _auth(client, login, "foreman")
    opened = client.post("/api/v1/rework-orders", headers=foreman, json={
        "request_id": str(uuid4()), "entity_qr": "DEMO-WIP-002", "quality_decision_id": rejected.id,
        "requested_route_step_id": assembly_step.id, "reason": "ДЕМО повтор",
    })
    assert opened.status_code == 201, opened.text
    _scan(client, login, "assembly2", "DEMO-WIP-002", "REWORK", 2)
    qc_headers = _auth(client, login, "qc")
    inspection_id = str(uuid4())
    reinspected = client.post("/api/v1/qc-inspections", headers=qc_headers, json=_body(
        _session(client)["id"], inspection_id, qr="DEMO-WIP-002", decision="REJECT", defect_code="DEMO-JOINT",
    ))
    assert reinspected.status_code == 200, reinspected.text
    assert reinspected.json()["inspection"]["mode"] == "REINSPECTION"
    seeded_db.expire_all()
    assert seeded_db.get(ReworkOrder, opened.json()["id"]).status == "REINSPECTED"
    foreman = _auth(client, login, "foreman")
    old = client.post("/api/v1/rework-orders", headers=foreman, json={
        "request_id": str(uuid4()), "entity_qr": "DEMO-WIP-002", "quality_decision_id": rejected.id,
        "requested_route_step_id": assembly_step.id, "reason": "Старое решение",
    })
    assert old.status_code == 409
    latest = seeded_db.scalar(select(QualityDecision).where(QualityDecision.request_id == inspection_id))
    new = client.post("/api/v1/rework-orders", headers=foreman, json={
        "request_id": str(uuid4()), "entity_qr": "DEMO-WIP-002", "quality_decision_id": latest.id,
        "requested_route_step_id": assembly_step.id, "reason": "Новый явный цикл",
    })
    assert new.status_code == 201, new.text


def test_qc_summary_excludes_other_shift_and_other_inspector(client: TestClient, seeded_db: Session, login) -> None:
    _auth(client, login, "qc")
    baseline = client.get("/api/v1/me/qc-shift-activity").json()
    qc = seeded_db.scalar(select(User).where(User.username == "qc"))
    admin = seeded_db.scalar(select(User).where(User.username == "admin"))
    seed_decision = seeded_db.scalar(select(QualityDecision).where(QualityDecision.inspector_user_id == qc.id))
    seed_event = seeded_db.get(OperationEvent, seed_decision.operation_event_id)
    entity = seeded_db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-WIP-008"))
    other_shift = Shift(
        code="DEMO-QC-OTHER", production_date="2026-10-24",
        starts_at=datetime(2026, 10, 24, 5, tzinfo=timezone.utc),
        ends_at=datetime(2026, 10, 24, 13, tzinfo=timezone.utc), status="CLOSED",
    )
    seeded_db.add(other_shift)
    seeded_db.flush()
    other_event = OperationEvent(
        id=str(uuid4()), payload_hash="f" * 64, shift_id=other_shift.id,
        work_session_id=seed_event.work_session_id, entity_id=entity.id, route_step_id=seed_event.route_step_id,
        user_id=qc.id, attempt_no=8, attempt_type="PRIMARY", event_type="COMPLETE",
        outcome="COMPLETED", status="ACCEPTED", code="EVENT_ACCEPTED",
    )
    admin_event = OperationEvent(
        id=str(uuid4()), payload_hash="1" * 64, shift_id=seed_event.shift_id,
        work_session_id=seed_event.work_session_id, entity_id=entity.id, route_step_id=seed_event.route_step_id,
        user_id=admin.id, attempt_no=9, attempt_type="PRIMARY", event_type="COMPLETE",
        outcome="COMPLETED", status="ACCEPTED", code="EVENT_ACCEPTED",
    )
    seeded_db.add_all([other_event, admin_event])
    seeded_db.flush()
    seeded_db.add_all([
        QualityDecision(request_id=str(uuid4()), entity_id=entity.id, shift_id=other_shift.id, operation_event_id=other_event.id, inspector_user_id=qc.id, decision="ACCEPT"),
        QualityDecision(request_id=str(uuid4()), entity_id=entity.id, shift_id=seed_event.shift_id, operation_event_id=admin_event.id, inspector_user_id=admin.id, decision="ACCEPT"),
    ])
    seeded_db.commit()
    summary = client.get("/api/v1/me/qc-shift-activity").json()
    assert summary["checked_count"] == baseline["checked_count"]
    assert {x["inspection_id"] for x in summary["recent_inspections"]} == {x["inspection_id"] for x in baseline["recent_inspections"]}
