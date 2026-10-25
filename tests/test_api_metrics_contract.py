from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    OperationEvent,
    QualityAudit,
    QualityDecision,
    ReworkOrder,
    RouteStep,
    Shift,
    TrackedEntity,
    User,
    WorkSession,
)


API = "/api/v1"


def _headers(user: dict) -> dict[str, str]:
    return {"X-CSRF-Token": user["csrf_token"]}


def _session_for(seeded_db: Session, username: str) -> WorkSession:
    session = seeded_db.scalar(
        select(WorkSession)
        .join(User, User.id == WorkSession.user_id)
        .where(User.username == username, WorkSession.ended_at.is_(None))
    )
    assert session is not None
    return session


def _shift(seeded_db: Session) -> Shift:
    shift = seeded_db.scalar(select(Shift).where(Shift.code == "DEMO-SHIFT-2026-10-25-D"))
    assert shift is not None
    return shift


def _new_wip(seeded_db: Session, suffix: str) -> TrackedEntity:
    template = seeded_db.scalar(
        select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-WIP-001")
    )
    assert template is not None
    entity = TrackedEntity(
        id=str(uuid4()),
        qr_code=f"DEMO-API-{suffix}",
        entity_type="WIP",
        model_id=template.model_id,
        route_version_id=template.route_version_id,
        status="IN_PROGRESS",
    )
    seeded_db.add(entity)
    seeded_db.commit()
    return entity


def _scan_payload(event_id: str, work_session_id: str, qr: str, **extra: object) -> dict:
    payload: dict[str, object] = {
        "event_id": event_id,
        "work_session_id": work_session_id,
        "subject_qr": qr,
        "event_type": "COMPLETE",
        "attempt_type": "PRIMARY",
        "attempt_no": 1,
    }
    payload.update(extra)
    return payload


def _calculation(client: TestClient, login: Callable, shift_id: str) -> dict:
    login(client, "admin")
    response = client.get(f"{API}/shifts/{shift_id}/calculation")
    assert response.status_code == 200, response.text
    return response.json()


def test_same_uuid_with_changed_qr_is_conflict(
    client: TestClient,
    seeded_db: Session,
    login: Callable,
) -> None:
    original = _new_wip(seeded_db, "UUID-ORIGINAL")
    changed = _new_wip(seeded_db, "UUID-CHANGED")
    work_session = _session_for(seeded_db, "solder")
    user = login(client, "solder")
    event_id = str(uuid4())

    accepted = client.post(
        f"{API}/operation-events",
        json=_scan_payload(event_id, work_session.id, original.qr_code),
        headers=_headers(user),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["duplicate"] is False

    conflict = client.post(
        f"{API}/operation-events",
        json=_scan_payload(event_id, work_session.id, changed.qr_code),
        headers=_headers(user),
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"


def test_new_uuid_semantic_duplicate_does_not_increase_e_fact(
    client: TestClient,
    seeded_db: Session,
    login: Callable,
) -> None:
    entity = _new_wip(seeded_db, "SEMANTIC")
    work_session = _session_for(seeded_db, "solder")
    shift_id = work_session.shift_id
    user = login(client, "solder")

    first = client.post(
        f"{API}/operation-events",
        json=_scan_payload(str(uuid4()), work_session.id, entity.qr_code),
        headers=_headers(user),
    )
    assert first.status_code == 200, first.text
    before = _calculation(client, login, shift_id)
    assert isinstance(before["production"]["e_fact"], str)

    user = login(client, "solder")
    duplicate = client.post(
        f"{API}/operation-events",
        json=_scan_payload(str(uuid4()), work_session.id, entity.qr_code),
        headers=_headers(user),
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["code"] == "SEMANTIC_DUPLICATE"

    after = _calculation(client, login, shift_id)
    assert after["production"]["e_fact"] == before["production"]["e_fact"]

    seeded_db.rollback()
    count = seeded_db.scalar(
        select(func.count()).select_from(OperationEvent).where(
            OperationEvent.entity_id == entity.id,
            OperationEvent.route_step_id == work_session.route_step_id,
            OperationEvent.attempt_type == "PRIMARY",
        )
    )
    assert count == 1


def test_worker_cannot_use_another_workers_session_or_assignment(
    client: TestClient,
    seeded_db: Session,
    login: Callable,
) -> None:
    other_session = _session_for(seeded_db, "assembly2")
    user = login(client, "assembly1")

    response = client.post(
        f"{API}/operation-events",
        json=_scan_payload(str(uuid4()), other_session.id, "DEMO-WIP-004"),
        headers=_headers(user),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "WORK_SESSION_OWNER_MISMATCH"


def test_no_independent_audit_returns_null_otk_quality(
    client: TestClient,
    seeded_db: Session,
    login: Callable,
) -> None:
    seeded_db.execute(delete(QualityAudit))
    seeded_db.commit()

    metrics = _calculation(client, login, _shift(seeded_db).id)

    assert metrics["otk"]["q_decision"] is None
    assert metrics["otk"]["kpi_raw"] is None
    assert metrics["otk"]["kpi_official"] is None
    assert "NO_AUDIT" in metrics["otk"]["reasons"]


def test_rework_event_does_not_credit_primary_output_again(
    client: TestClient,
    seeded_db: Session,
    login: Callable,
) -> None:
    entity = seeded_db.scalar(
        select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-WIP-002")
    )
    decision = seeded_db.scalar(
        select(QualityDecision).where(
            QualityDecision.entity_id == entity.id,
            QualityDecision.decision == "REJECT",
        )
    )
    assembly_step = seeded_db.scalar(
        select(RouteStep).where(RouteStep.code == "DEMO-ASSEMBLE")
    )
    assembly_session = _session_for(seeded_db, "assembly2")
    assert entity is not None and decision is not None and assembly_step is not None
    shift_id = assembly_session.shift_id
    before = _calculation(client, login, shift_id)

    qc_user = login(client, "qc")
    order = client.post(
        f"{API}/rework-orders",
        json={
            "request_id": str(uuid4()),
            "entity_qr": entity.qr_code,
            "quality_decision_id": decision.id,
            "requested_route_step_id": assembly_step.id,
            "reason": "DEMO API rework contract",
        },
        headers=_headers(qc_user),
    )
    assert order.status_code == 201, order.text
    assert order.json()["status"] == "OPEN"

    assembly_user = login(client, "assembly2")
    rework = client.post(
        f"{API}/operation-events",
        json=_scan_payload(
            str(uuid4()),
            assembly_session.id,
            entity.qr_code,
            attempt_type="REWORK",
            attempt_no=2,
        ),
        headers=_headers(assembly_user),
    )
    assert rework.status_code == 200, rework.text
    assert rework.json()["attempt_type"] == "REWORK"

    after = _calculation(client, login, shift_id)
    assert after["production"]["e_fact"] == before["production"]["e_fact"]

    seeded_db.rollback()
    saved_order = seeded_db.scalar(
        select(ReworkOrder).where(ReworkOrder.id == order.json()["id"])
    )
    assert saved_order is not None
    assert saved_order.status == "READY_FOR_QC"
