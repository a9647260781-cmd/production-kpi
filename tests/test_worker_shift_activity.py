from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    OperationEvent,
    ProductionRow,
    RouteStep,
    Shift,
    ShiftAssignment,
    TrackedEntity,
    User,
    WorkSession,
    Workstation,
)


def _login(client: TestClient, login, username: str) -> None:
    login(client, username)


def _summary(client: TestClient, limit: int = 10):
    return client.get(f"/api/v1/me/shift-activity?limit={limit}")


def test_activity_is_scoped_to_authenticated_actor_and_active_shift(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    assembly1 = seeded_db.scalar(select(User).where(User.username == "assembly1"))
    shift = seeded_db.scalar(select(Shift).where(Shift.status == "RUNNING"))
    row = seeded_db.scalar(select(ProductionRow).where(ProductionRow.code == "DEMO-ASM-01"))
    workstation = seeded_db.scalar(select(Workstation).where(Workstation.row_id == row.id))
    step = seeded_db.scalar(select(RouteStep).where(RouteStep.code == "DEMO-ASSEMBLE"))
    entity = seeded_db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-WIP-008"))
    assert assembly1 and shift and row and workstation and step and entity

    other_shift = Shift(
        code="DEMO-OTHER-SHIFT",
        production_date="2026-10-24",
        starts_at=datetime(2026, 10, 24, 5, tzinfo=timezone.utc),
        ends_at=datetime(2026, 10, 24, 13, tzinfo=timezone.utc),
        status="CLOSED",
    )
    seeded_db.add(other_shift)
    seeded_db.flush()
    assignment = ShiftAssignment(
        shift_id=other_shift.id,
        employee_id=assembly1.employee_id,
        row_id=row.id,
        workstation_id=workstation.id,
        route_step_id=step.id,
        starts_at=other_shift.starts_at,
        ends_at=other_shift.ends_at,
        status="ENDED",
    )
    seeded_db.add(assignment)
    seeded_db.flush()
    work_session = WorkSession(
        user_id=assembly1.id,
        employee_id=assembly1.employee_id,
        shift_id=other_shift.id,
        row_id=row.id,
        workstation_id=workstation.id,
        route_step_id=step.id,
        assignment_id=assignment.id,
        started_at=other_shift.starts_at,
        ended_at=other_shift.ends_at,
    )
    seeded_db.add(work_session)
    seeded_db.flush()
    seeded_db.add(OperationEvent(
        id=str(uuid4()),
        payload_hash="b" * 64,
        shift_id=other_shift.id,
        work_session_id=work_session.id,
        entity_id=entity.id,
        route_step_id=step.id,
        user_id=assembly1.id,
        attempt_no=1,
        attempt_type="PRIMARY",
        event_type="COMPLETE",
        outcome="COMPLETED",
        status="ACCEPTED",
        code="EVENT_ACCEPTED",
    ))
    seeded_db.commit()

    _login(client, login, "assembly1")
    response = _summary(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["shift"]["id"] == shift.id
    assert body["employee"]["id"] == assembly1.employee_id
    assert body["context"]["row"]["code"] == "DEMO-ASM-01"
    assert body["context"]["route_step"]["code"] == "DEMO-ASSEMBLE"
    assert body["primary_completed"] == 1
    assert body["rework_completed"] == 0
    assert body["corrected_primary"] == 0
    assert {event["subject_qr"] for event in body["recent_events"]} == {"DEMO-WIP-001"}
    assert "DEMO-WIP-002" not in {event["subject_qr"] for event in body["recent_events"]}
    assert "DEMO-WIP-008" not in {event["subject_qr"] for event in body["recent_events"]}

    _login(client, login, "planner")
    denied = _summary(client)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "CAPABILITY_REQUIRED"


def test_retry_does_not_increment_and_rework_pending_are_separate(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    user = login(client, "solder")
    session_response = client.get("/api/v1/work-sessions")
    session = next(item for item in session_response.json()["items"] if item["ended_at"] is None)
    baseline = _summary(client).json()
    event_id = str(uuid4())
    request = {
        "event_id": event_id,
        "work_session_id": session["id"],
        "subject_qr": "DEMO-WIP-004",
        "event_type": "COMPLETE",
        "attempt_type": "PRIMARY",
        "attempt_no": 1,
    }
    accepted = client.post("/api/v1/operation-events", headers={"X-CSRF-Token": user["csrf_token"]}, json=request)
    retry = client.post("/api/v1/operation-events", headers={"X-CSRF-Token": user["csrf_token"]}, json=request)
    assert accepted.status_code == 200 and retry.status_code == 200
    assert retry.json()["duplicate"] is True

    db_user = seeded_db.scalar(select(User).where(User.username == "solder"))
    work_session = seeded_db.get(WorkSession, session["id"])
    step = seeded_db.get(RouteStep, work_session.route_step_id)
    rework_entity = seeded_db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-WIP-004"))
    pending_entity = seeded_db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-WIP-005"))
    assert db_user and work_session and step and rework_entity and pending_entity
    seeded_db.add_all([
        OperationEvent(
            id=str(uuid4()), payload_hash="c" * 64, shift_id=work_session.shift_id,
            work_session_id=work_session.id, entity_id=rework_entity.id, route_step_id=step.id,
            user_id=db_user.id, attempt_no=2, attempt_type="REWORK", event_type="COMPLETE",
            outcome="COMPLETED", status="ACCEPTED", code="EVENT_ACCEPTED",
        ),
        OperationEvent(
            id=str(uuid4()), payload_hash="d" * 64, shift_id=work_session.shift_id,
            work_session_id=work_session.id, entity_id=pending_entity.id, route_step_id=step.id,
            user_id=db_user.id, attempt_no=9, attempt_type="PRIMARY", event_type="COMPLETE",
            outcome="PENDING", status="NEEDS_REVIEW", code="PENDING_REVIEW",
        ),
    ])
    seeded_db.commit()

    body = _summary(client).json()
    assert body["primary_completed"] == baseline["primary_completed"] + 1
    assert body["rework_completed"] == baseline["rework_completed"] + 1
    assert sum(event["event_id"] == event_id for event in body["recent_events"]) == 1
    assert any(event["display_status"] == "REWORK" for event in body["recent_events"])
    assert any(event["display_status"] == "NEEDS_REVIEW" for event in body["recent_events"])
    assert _summary(client, limit=11).status_code == 422


def test_correction_by_another_actor_marks_original_and_removes_primary_credit(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    original = seeded_db.scalar(
        select(OperationEvent)
        .join(User, User.id == OperationEvent.user_id)
        .where(User.username == "assembly1", OperationEvent.event_type == "COMPLETE")
    )
    admin = seeded_db.scalar(select(User).where(User.username == "admin"))
    assert original and admin
    seeded_db.add(OperationEvent(
        id=str(uuid4()),
        payload_hash="e" * 64,
        shift_id=original.shift_id,
        work_session_id=original.work_session_id,
        entity_id=original.entity_id,
        route_step_id=original.route_step_id,
        plan_line_id=original.plan_line_id,
        user_id=admin.id,
        attempt_no=original.attempt_no,
        attempt_type="PRIMARY",
        event_type="CORRECTION",
        outcome="CANCELLED",
        status="ACCEPTED",
        code="DEMO_CORRECTION",
        correction_of_id=original.id,
        reason="Исправлено другим пользователем",
    ))
    seeded_db.commit()

    _login(client, login, "assembly1")
    body = _summary(client).json()
    assert body["primary_completed"] == 0
    assert body["corrected_primary"] == 1
    assert len(body["recent_events"]) == 1
    recent = body["recent_events"][0]
    assert recent["event_id"] == original.id
    assert recent["status"] == "ACCEPTED"
    assert recent["display_status"] == "CORRECTED"
    assert recent["corrected"] is True


def test_no_active_shift_is_not_reported_as_zero_activity(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    shift = seeded_db.scalar(select(Shift).where(Shift.status == "RUNNING"))
    assert shift
    shift.status = "CLOSED"
    seeded_db.commit()
    _login(client, login, "assembly1")
    response = _summary(client)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACTIVE_SHIFT_NOT_FOUND"
