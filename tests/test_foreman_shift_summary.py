from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    OperationEvent,
    ProductionRow,
    QualityDecision,
    ReworkOrder,
    RouteStep,
    Shift,
    ShiftAssignment,
    TrackedEntity,
    User,
    UserRole,
    WorkSession,
)
from app.seed import upgrade_demo_foreman_scope
from app.services import canonical_payload_hash


def _headers(user: dict) -> dict[str, str]:
    return {"X-CSRF-Token": user["csrf_token"]}


def _foreman_summary(client: TestClient, login) -> dict:
    login(client, "foreman")
    response = client.get("/api/v1/me/foreman-shift-summary")
    assert response.status_code == 200, response.text
    return response.json()


def _event(
    db: Session,
    *,
    session: WorkSession,
    entity: TrackedEntity,
    attempt_type: str,
    attempt_no: int,
    event_type: str = "COMPLETE",
    correction_of_id: str | None = None,
) -> OperationEvent:
    event_id = str(uuid4())
    event = OperationEvent(
        id=event_id,
        payload_hash=canonical_payload_hash({"id": event_id}),
        shift_id=session.shift_id,
        work_session_id=session.id,
        entity_id=entity.id,
        route_step_id=session.route_step_id,
        user_id=session.user_id,
        attempt_no=attempt_no,
        attempt_type=attempt_type,
        event_type=event_type,
        outcome="COMPLETED",
        status="ACCEPTED",
        code="EVENT_ACCEPTED" if event_type == "COMPLETE" else "EVENT_CORRECTED",
        correction_of_id=correction_of_id,
    )
    db.add(event)
    db.flush()
    return event


def test_foreman_summary_is_server_scoped_and_roster_is_not_presence(
    client: TestClient, seeded_db: Session, login
) -> None:
    summary = _foreman_summary(client, login)
    assert summary["row"]["code"] == "DEMO-ASM-01"
    assert {item["employee"]["display_name"] for item in summary["roster"]} >= {
        "Оператор сборки 1",
        "Бригадир",
    }
    assert "не присутствие онлайн" in summary["note"].lower()
    assert all("assignment_status" in item for item in summary["roster"])

    me = client.get("/api/v1/auth/me").json()["user"]
    client.post("/api/v1/auth/logout", headers=_headers(me))
    login(client, "admin")
    forbidden = client.get("/api/v1/me/foreman-shift-summary")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "FOREMAN_ROLE_REQUIRED"


def test_demo_scope_upgrade_is_idempotent_and_fallback_never_becomes_global(
    client: TestClient, seeded_db: Session, login
) -> None:
    foreman = seeded_db.scalar(select(User).where(User.username == "foreman"))
    role = seeded_db.scalar(select(UserRole).where(UserRole.user_id == foreman.id, UserRole.role == "FOREMAN"))
    role.row_id = None
    seeded_db.commit()

    assert upgrade_demo_foreman_scope(seeded_db) is True
    assert upgrade_demo_foreman_scope(seeded_db) is False
    assert role.row_id == seeded_db.scalar(select(ProductionRow.id).where(ProductionRow.code == "DEMO-ASM-01"))
    assert seeded_db.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.action == "DEMO_FOREMAN_SCOPE_UPGRADED"
    )) == 1

    role.row_id = None
    seeded_db.commit()
    summary = _foreman_summary(client, login)
    assert summary["row"]["code"] == "DEMO-ASM-01"

    shift = seeded_db.scalar(select(Shift).where(Shift.status == "RUNNING"))
    row2 = seeded_db.scalar(select(ProductionRow).where(ProductionRow.code == "DEMO-ASM-02"))
    source = seeded_db.scalar(select(ShiftAssignment).where(
        ShiftAssignment.shift_id == shift.id,
        ShiftAssignment.employee_id == foreman.employee_id,
    ))
    row2_assignment = seeded_db.scalar(select(ShiftAssignment).where(
        ShiftAssignment.shift_id == shift.id,
        ShiftAssignment.row_id == row2.id,
    ))
    seeded_db.add(ShiftAssignment(
        shift_id=shift.id,
        employee_id=foreman.employee_id,
        row_id=row2.id,
        workstation_id=row2_assignment.workstation_id,
        route_step_id=source.route_step_id,
        starts_at=source.starts_at,
        ends_at=source.ends_at,
        status="ACTIVE",
    ))
    seeded_db.commit()
    ambiguous = client.get("/api/v1/me/foreman-shift-summary")
    assert ambiguous.status_code == 409
    assert ambiguous.json()["error"]["code"] == "FOREMAN_ROW_SCOPE_AMBIGUOUS"


def test_row_counts_use_event_session_and_exclude_corrected_primary(
    client: TestClient, seeded_db: Session, login
) -> None:
    before = _foreman_summary(client, login)
    session = seeded_db.scalar(select(WorkSession).join(User).where(User.username == "assembly1"))
    route = seeded_db.get(RouteStep, session.route_step_id).route_version_id

    entities = []
    for index in range(3):
        entity = TrackedEntity(
            qr_code=f"TEST-FOREMAN-COUNT-{index}",
            entity_type="WIP",
            route_version_id=route,
            status="ACTIVE",
        )
        seeded_db.add(entity)
        seeded_db.flush()
        entities.append(entity)
    _event(seeded_db, session=session, entity=entities[0], attempt_type="PRIMARY", attempt_no=10)
    _event(seeded_db, session=session, entity=entities[1], attempt_type="REWORK", attempt_no=11)
    corrected = _event(seeded_db, session=session, entity=entities[2], attempt_type="PRIMARY", attempt_no=12)
    _event(
        seeded_db,
        session=session,
        entity=entities[2],
        attempt_type="PRIMARY",
        attempt_no=13,
        event_type="CORRECTION",
        correction_of_id=corrected.id,
    )
    seeded_db.commit()

    after = client.get("/api/v1/me/foreman-shift-summary").json()
    assert after["primary_completed"] == before["primary_completed"] + 1
    assert after["rework_completed"] == before["rework_completed"] + 1


def test_route_rejection_is_durable_deduplicated_and_has_no_credit(
    client: TestClient, seeded_db: Session, login
) -> None:
    worker = login(client, "assembly1")
    session = seeded_db.scalar(select(WorkSession).where(WorkSession.user_id == worker["id"]))
    step = seeded_db.get(RouteStep, session.route_step_id)
    entity = TrackedEntity(
        qr_code="TEST-FOREMAN-ROUTE-BAD",
        entity_type=step.entity_type,
        route_version_id=step.route_version_id,
        status="ACTIVE",
    )
    seeded_db.add(entity)
    seeded_db.commit()
    event_id = str(uuid4())
    body = {
        "event_id": event_id,
        "work_session_id": session.id,
        "subject_qr": entity.qr_code,
        "event_type": "COMPLETE",
        "attempt_type": "PRIMARY",
        "attempt_no": 1,
    }
    first = client.post("/api/v1/operation-events", headers=_headers(worker), json=body)
    second = client.post("/api/v1/operation-events", headers=_headers(worker), json=body)
    assert first.status_code == second.status_code == 409
    assert first.json()["error"]["code"] == second.json()["error"]["code"] == "ROUTE_VIOLATION"
    assert seeded_db.get(OperationEvent, event_id) is None
    assert seeded_db.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.action == "OPERATION_SCAN_REJECTED",
        AuditEvent.object_id == event_id,
    )) == 1

    changed = client.post(
        "/api/v1/operation-events",
        headers=_headers(worker),
        json={**body, "subject_qr": "DIFFERENT-QR"},
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"

    me = client.get("/api/v1/auth/me").json()["user"]
    client.post("/api/v1/auth/logout", headers=_headers(me))
    summary = _foreman_summary(client, login)
    problem = next(item for item in summary["problems"] if item["qr"] == entity.qr_code)
    assert problem["kind"] == "SCAN_REJECTED"
    assert problem["status"] == "REJECTED_TERMINAL"
    assert problem["worker"]["display_name"] == "Оператор сборки 1"
    assert problem["allowed_actions"] == []


def test_foreman_summary_excludes_other_row_rejection_and_uuid_is_actor_bound(
    client: TestClient, seeded_db: Session, login
) -> None:
    worker2 = login(client, "assembly2")
    session2 = seeded_db.scalar(select(WorkSession).where(WorkSession.user_id == worker2["id"]))
    step = seeded_db.get(RouteStep, session2.route_step_id)
    entity = TrackedEntity(
        qr_code="TEST-FOREMAN-ROW2-ROUTE-BAD",
        entity_type=step.entity_type,
        route_version_id=step.route_version_id,
        status="ACTIVE",
    )
    seeded_db.add(entity)
    seeded_db.commit()
    event_id = str(uuid4())
    body = {
        "event_id": event_id,
        "work_session_id": session2.id,
        "subject_qr": entity.qr_code,
        "event_type": "COMPLETE",
        "attempt_type": "PRIMARY",
        "attempt_no": 1,
    }
    rejected = client.post("/api/v1/operation-events", headers=_headers(worker2), json=body)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "ROUTE_VIOLATION"

    worker1 = login(client, "assembly1")
    foreign = client.post(
        "/api/v1/operation-events",
        headers=_headers(worker1),
        json={**body, "work_session_id": seeded_db.scalar(
            select(WorkSession.id).where(WorkSession.user_id == worker1["id"])
        )},
    )
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "EVENT_OWNER_MISMATCH"
    assert foreign.json()["submission"]["terminal"] is False

    summary = _foreman_summary(client, login)
    assert entity.qr_code not in {item["qr"] for item in summary["problems"]}


def test_row_output_remains_on_original_work_session_after_employee_transfer(
    client: TestClient, seeded_db: Session, login
) -> None:
    before = _foreman_summary(client, login)
    assembly1 = seeded_db.scalar(select(User).where(User.username == "assembly1"))
    session1 = seeded_db.scalar(select(WorkSession).where(WorkSession.user_id == assembly1.id))
    source = seeded_db.get(ShiftAssignment, session1.assignment_id)
    route = seeded_db.get(RouteStep, session1.route_step_id).route_version_id
    entity = TrackedEntity(
        qr_code="TEST-FOREMAN-BEFORE-TRANSFER",
        entity_type="WIP",
        route_version_id=route,
        status="ACTIVE",
    )
    seeded_db.add(entity)
    seeded_db.flush()
    _event(seeded_db, session=session1, entity=entity, attempt_type="PRIMARY", attempt_no=60)

    row2 = seeded_db.scalar(select(ProductionRow).where(ProductionRow.code == "DEMO-ASM-02"))
    row2_template = seeded_db.scalar(select(ShiftAssignment).where(
        ShiftAssignment.shift_id == source.shift_id,
        ShiftAssignment.row_id == row2.id,
    ))
    source.status = "ENDED"
    source.ends_at = source.starts_at + timedelta(hours=4)
    transferred = ShiftAssignment(
        shift_id=source.shift_id,
        employee_id=source.employee_id,
        row_id=row2.id,
        workstation_id=row2_template.workstation_id,
        route_step_id=source.route_step_id,
        starts_at=source.ends_at,
        ends_at=row2_template.ends_at,
        status="ACTIVE",
    )
    seeded_db.add(transferred)
    seeded_db.flush()
    seeded_db.add(WorkSession(
        user_id=assembly1.id,
        employee_id=source.employee_id,
        shift_id=source.shift_id,
        row_id=row2.id,
        workstation_id=transferred.workstation_id,
        route_step_id=transferred.route_step_id,
        assignment_id=transferred.id,
        started_at=transferred.starts_at,
    ))
    seeded_db.commit()

    after = client.get("/api/v1/me/foreman-shift-summary").json()
    assert after["primary_completed"] == before["primary_completed"] + 1
    original = next(item for item in after["roster"] if item["assignment_id"] == source.id)
    assert original["assignment_status"] == "ENDED"


def test_ambiguous_rework_is_hidden_until_effective_actual_row_evidence(
    client: TestClient, seeded_db: Session, login
) -> None:
    decision = seeded_db.scalar(select(QualityDecision).where(QualityDecision.decision == "REJECT"))
    entity = seeded_db.get(TrackedEntity, decision.entity_id)
    assembly_step = seeded_db.scalar(select(RouteStep).where(RouteStep.row_id.is_(None)))
    order = ReworkOrder(
        request_id=str(uuid4()),
        entity_id=entity.id,
        quality_decision_id=decision.id,
        requested_route_step_id=assembly_step.id,
        status="OPEN",
        created_by_id=decision.inspector_user_id,
        reason="TEST ambiguous row",
    )
    seeded_db.add(order)
    seeded_db.commit()

    before = _foreman_summary(client, login)
    assert order.id not in {item["id"] for item in before["reworks"]}

    session = seeded_db.scalar(select(WorkSession).join(User).where(User.username == "assembly1"))
    event = _event(seeded_db, session=session, entity=entity, attempt_type="REWORK", attempt_no=50)
    event.server_received_at = order.created_at + timedelta(seconds=1)
    seeded_db.commit()

    after = client.get("/api/v1/me/foreman-shift-summary").json()
    rework = next(item for item in after["reworks"] if item["id"] == order.id)
    assert rework["qr"] == entity.qr_code
    assert rework["requested_route_step"]["id"] == assembly_step.id
    assert rework["allowed_actions"] == []
