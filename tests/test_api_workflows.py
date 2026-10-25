from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GenealogyLink, OperationEvent, ProductModel, QualityDecision, RouteStep, TrackedEntity


def _auth(client: TestClient, login, username: str) -> dict[str, str]:
    user = login(client, username)
    return {"X-CSRF-Token": user["csrf_token"]}


def _bootstrap(client: TestClient) -> dict:
    response = client.get("/api/v1/bootstrap")
    assert response.status_code == 200, response.text
    return response.json()


def _work_session(client: TestClient) -> dict:
    response = client.get("/api/v1/work-sessions")
    assert response.status_code == 200, response.text
    active = [item for item in response.json()["items"] if item["ended_at"] is None]
    assert active
    return active[0]


def test_auth_bootstrap_and_server_rbac(client: TestClient, login) -> None:
    headers = _auth(client, login, "assembly1")
    bootstrap = _bootstrap(client)
    assert len(bootstrap["rows"]) == 5
    assert bootstrap["synthetic"] is True
    assert "scan" in bootstrap["capabilities"]
    assert "manage_standards" not in bootstrap["capabilities"]

    denied = client.post(
        "/api/v1/standards",
        headers=headers,
        json={"model_id": str(uuid4()), "status": "DRAFT", "effective_from": "2026-10-25T00:00:00Z", "values": []},
    )
    assert denied.status_code == 403
    denied = client.post(f"/api/v1/shifts/{bootstrap['active_shift']['id']}/approve", headers=headers)
    assert denied.status_code == 403


def test_scan_retry_semantic_duplicate_and_route_validation(client: TestClient, seeded_db: Session, login) -> None:
    headers = _auth(client, login, "solder")
    work_session = _work_session(client)
    event_id = str(uuid4())
    body = {
        "event_id": event_id,
        "work_session_id": work_session["id"],
        "subject_qr": "DEMO-WIP-004",
        "event_type": "COMPLETE",
        "attempt_type": "PRIMARY",
        "attempt_no": 1,
    }
    accepted = client.post("/api/v1/operation-events", headers=headers, json=body)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["duplicate"] is False
    assert accepted.json()["accepted"] is True and accepted.json()["terminal"] is True

    retry = client.post("/api/v1/operation-events", headers=headers, json=body)
    assert retry.status_code == 200
    assert retry.json()["duplicate"] is True
    assert retry.json()["accepted"] is True and retry.json()["terminal"] is True

    semantic_body = {**body, "event_id": str(uuid4())}
    semantic = client.post("/api/v1/operation-events", headers=headers, json=semantic_body)
    assert semantic.status_code == 200
    assert semantic.json()["code"] == "SEMANTIC_DUPLICATE"
    entity_id = seeded_db.scalar(select(TrackedEntity.id).where(TrackedEntity.qr_code == "DEMO-WIP-004"))
    seeded_db.expire_all()
    count = seeded_db.scalar(select(func.count()).select_from(OperationEvent).where(OperationEvent.entity_id == entity_id))
    assert count == 1

    _auth(client, login, "assembly1")
    assembly_session = _work_session(client)
    violation = client.post(
        "/api/v1/operation-events",
        headers={"X-CSRF-Token": client.get("/api/v1/auth/me").json()["user"]["csrf_token"]},
        json={**body, "event_id": str(uuid4()), "work_session_id": assembly_session["id"], "subject_qr": "DEMO-WIP-005"},
    )
    assert violation.status_code == 409
    assert violation.json()["error"]["code"] == "ROUTE_VIOLATION"


def test_same_uuid_changed_body_and_foreign_actor_are_blocked(client: TestClient, login) -> None:
    headers = _auth(client, login, "solder")
    work_session = _work_session(client)
    event_id = str(uuid4())
    original = {
        "event_id": event_id, "work_session_id": work_session["id"], "subject_qr": "DEMO-WIP-005",
        "event_type": "COMPLETE", "attempt_type": "PRIMARY", "attempt_no": 1,
    }
    assert client.post("/api/v1/operation-events", headers=headers, json=original).status_code == 200
    changed = client.post("/api/v1/operation-events", headers=headers, json={**original, "subject_qr": "DEMO-WIP-006"})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"

    foreign_headers = _auth(client, login, "assembly1")
    foreign = client.post("/api/v1/operation-events", headers=foreign_headers, json=original)
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "EVENT_OWNER_MISMATCH"


def test_invalid_qr_returns_terminal_rejection_then_correct_scan_works(client: TestClient, login) -> None:
    headers = _auth(client, login, "solder")
    session = _work_session(client)
    rejected = client.post("/api/v1/operation-events", headers=headers, json={
        "event_id": str(uuid4()), "work_session_id": session["id"], "subject_qr": "UNKNOWN-QR",
        "event_type": "COMPLETE", "attempt_type": "PRIMARY", "attempt_no": 1,
    })
    assert rejected.status_code == 404
    assert rejected.json()["error"]["code"] == "ENTITY_NOT_FOUND"
    assert rejected.json()["submission"]["terminal"] is True
    assert rejected.json()["submission"]["accepted"] is False

    accepted = client.post("/api/v1/operation-events", headers=headers, json={
        "event_id": str(uuid4()), "work_session_id": session["id"], "subject_qr": "DEMO-WIP-004",
        "event_type": "COMPLETE", "attempt_type": "PRIMARY", "attempt_no": 1,
    })
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted"] is True


def test_genealogy_attach_replace_keeps_history(client: TestClient, seeded_db: Session, login) -> None:
    headers = _auth(client, login, "foreman")
    attached = client.post("/api/v1/genealogy/actions", headers=headers, json={
        "request_id": str(uuid4()), "action": "ATTACH", "parent_qr": "DEMO-WIP-004", "child_qr": "DEMO-COMP-MOTOR-004A",
    })
    assert attached.status_code == 201, attached.text
    replaced = client.post("/api/v1/genealogy/actions", headers=headers, json={
        "request_id": str(uuid4()), "action": "REPLACE", "parent_qr": "DEMO-WIP-004",
        "child_qr": "DEMO-COMP-MOTOR-004A", "replacement_qr": "DEMO-COMP-MOTOR-004B", "reason": "ДЕМО замена",
    })
    assert replaced.status_code == 201, replaced.text
    seeded_db.expire_all()
    old = seeded_db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-COMP-MOTOR-004A"))
    new = seeded_db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-COMP-MOTOR-004B"))
    old_link = seeded_db.scalar(select(GenealogyLink).where(GenealogyLink.child_entity_id == old.id))
    new_link = seeded_db.scalar(select(GenealogyLink).where(GenealogyLink.child_entity_id == new.id))
    assert old_link.active is False and old_link.ended_at is not None
    assert new_link.active is True and new_link.action == "REPLACE"


def test_qc_fail_rework_reinspect_and_independent_audit(client: TestClient, seeded_db: Session, login) -> None:
    headers = _auth(client, login, "foreman")
    rejected = seeded_db.scalar(select(QualityDecision).where(QualityDecision.decision == "REJECT"))
    assembly_step = seeded_db.scalar(select(RouteStep).where(RouteStep.code == "DEMO-ASSEMBLE"))
    opened = client.post("/api/v1/rework-orders", headers=headers, json={
        "request_id": str(uuid4()), "entity_qr": "DEMO-WIP-002", "quality_decision_id": rejected.id,
        "requested_route_step_id": assembly_step.id, "reason": "Исправить ДЕМО-дефект",
    })
    assert opened.status_code == 201, opened.text

    headers = _auth(client, login, "assembly2")
    session = _work_session(client)
    rework = client.post("/api/v1/operation-events", headers=headers, json={
        "event_id": str(uuid4()), "work_session_id": session["id"], "subject_qr": "DEMO-WIP-002",
        "event_type": "COMPLETE", "attempt_type": "REWORK", "attempt_no": 2,
    })
    assert rework.status_code == 200, rework.text

    headers = _auth(client, login, "qc")
    session = _work_session(client)
    reinspect = client.post("/api/v1/operation-events", headers=headers, json={
        "event_id": str(uuid4()), "work_session_id": session["id"], "subject_qr": "DEMO-WIP-002",
        "event_type": "COMPLETE", "attempt_type": "REWORK", "attempt_no": 2,
    })
    assert reinspect.status_code == 200, reinspect.text
    decision = client.post("/api/v1/quality/decisions", headers=headers, json={
        "request_id": str(uuid4()), "entity_qr": "DEMO-WIP-002", "decision": "ACCEPT", "note": "После rework",
    })
    assert decision.status_code == 201, decision.text

    headers = _auth(client, login, "auditor")
    audit = client.post("/api/v1/quality/audits", headers=headers, json={
        "request_id": str(uuid4()), "decision_id": decision.json()["id"], "result": "CONFIRMED",
    })
    assert audit.status_code == 201, audit.text


def test_approval_snapshot_and_csv_are_frozen(client: TestClient, seeded_db: Session, login) -> None:
    headers = _auth(client, login, "supervisor")
    shift_id = _bootstrap(client)["active_shift"]["id"]
    approved = client.post(f"/api/v1/shifts/{shift_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    snapshot_metrics = approved.json()["metrics"]
    assert snapshot_metrics["approval_status"] == "APPROVED"

    headers = _auth(client, login, "admin")
    model = seeded_db.scalar(select(ProductModel))
    steps = list(seeded_db.scalars(select(RouteStep).order_by(RouteStep.sequence)))
    changed = client.post("/api/v1/standards", headers=headers, json={
        "model_id": model.id, "status": "APPROVED", "effective_from": "2026-10-26T00:00:00Z",
        "reason": "Проверка frozen snapshot",
        "values": [{"route_step_id": step.id, "norm_minutes": "99"} for step in steps],
    })
    assert changed.status_code == 201, changed.text
    report = client.get(f"/api/v1/reports/{shift_id}")
    assert report.status_code == 200
    assert report.json()["frozen"] is True
    assert report.json()["calculation"] == snapshot_metrics
    csv_response = client.get(f"/api/v1/reports/{shift_id}.csv")
    assert csv_response.status_code == 200
    assert "attachment" in csv_response.headers["content-disposition"]
    assert str(snapshot_metrics["kpi_official"]) in csv_response.text


def test_plan_and_standard_patch_preserve_unmentioned_lines(client: TestClient, seeded_db: Session, login) -> None:
    _auth(client, login, "planner")
    shift_id = _bootstrap(client)["active_shift"]["id"]
    headers = _auth(client, login, "planner")
    before = client.get(f"/api/v1/plans?shift_id={shift_id}").json()["items"][0]
    edited = before["lines"][0]
    response = client.post("/api/v1/plans", headers=headers, json={
        "shift_id": shift_id, "status": "APPROVED", "reason": "PATCH одной строки",
        "lines": [{
            "key": edited["key"], "model_id": edited["model_id"],
            "route_step_id": edited["route_step_id"], "row_id": edited["row_id"],
            "planned_qty": edited["planned_qty"] + 1, "norm_minutes": edited["norm_minutes"],
        }],
    })
    assert response.status_code == 201, response.text
    after = client.get(f"/api/v1/plans?shift_id={shift_id}").json()["items"][0]
    assert len(after["lines"]) == len(before["lines"])

    headers = _auth(client, login, "admin")
    before_standards = client.get("/api/v1/standards").json()["items"][0]
    one = before_standards["values"][0]
    changed = client.post("/api/v1/standards", headers=headers, json={
        "model_id": before_standards["model_id"], "status": "APPROVED",
        "effective_from": "2026-10-26T00:00:00Z", "reason": "PATCH одной нормы",
        "values": [{"route_step_id": one["route_step_id"], "norm_minutes": "7"}],
    })
    assert changed.status_code == 201, changed.text
    after_standards = client.get("/api/v1/standards").json()["items"][0]
    assert len(after_standards["values"]) == len(before_standards["values"])


def test_assignment_overlap_requires_explicit_transfer(client: TestClient, login) -> None:
    headers = _auth(client, login, "planner")
    bootstrap = _bootstrap(client)
    shift_id = bootstrap["active_shift"]["id"]
    assignments = client.get(f"/api/v1/assignments?shift_id={shift_id}").json()["items"]
    source = next(item for item in assignments if item["status"] == "ACTIVE")
    assembly_row = next(row for row in bootstrap["rows"] if row["category"] == "ASSEMBLY" and row["id"] != source["row_id"])
    workstation = next(item for item in bootstrap["workstations"] if item["row_id"] == assembly_row["id"])
    assembly_step = next(item for item in bootstrap["route_steps"] if "ASSEMBLE" in item["code"])
    body = {
        "employee_id": source["employee_id"], "row_id": assembly_row["id"],
        "workstation_id": workstation["id"], "route_step_id": assembly_step["id"],
        "starts_at": "2026-10-25T09:00:00Z", "ends_at": "2026-10-25T13:00:00Z",
    }
    overlap = client.post(f"/api/v1/shifts/{shift_id}/assignments", headers=headers, json=body)
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "ASSIGNMENT_OVERLAP"
    transfer = client.post(f"/api/v1/shifts/{shift_id}/assignments", headers=headers, json={**body, "transfer_from_assignment_id": source["id"]})
    assert transfer.status_code == 201, transfer.text


def test_scan_is_blocked_after_shift_approval(client: TestClient, login) -> None:
    solder_headers = _auth(client, login, "solder")
    session = _work_session(client)
    accepted_body = {
        "event_id": str(uuid4()), "work_session_id": session["id"], "subject_qr": "DEMO-WIP-004",
        "event_type": "COMPLETE", "attempt_type": "PRIMARY", "attempt_no": 1,
    }
    assert client.post("/api/v1/operation-events", headers=solder_headers, json=accepted_body).status_code == 200
    supervisor_headers = _auth(client, login, "supervisor")
    shift_id = _bootstrap(client)["active_shift"]["id"]
    approved = client.post(f"/api/v1/shifts/{shift_id}/approve", headers=supervisor_headers)
    assert approved.status_code == 200, approved.text
    solder_headers = _auth(client, login, "solder")
    retry = client.post("/api/v1/operation-events", headers=solder_headers, json=accepted_body)
    assert retry.status_code == 200
    assert retry.json()["duplicate"] is True
    response = client.post("/api/v1/operation-events", headers=solder_headers, json={
        "event_id": str(uuid4()), "work_session_id": session["id"], "subject_qr": "DEMO-WIP-005",
        "event_type": "COMPLETE", "attempt_type": "PRIMARY", "attempt_no": 1,
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SHIFT_NOT_MUTABLE"


def test_scan_is_blocked_after_assignment_transfer(client: TestClient, login) -> None:
    solder_headers = _auth(client, login, "solder")
    old_session = _work_session(client)
    planner_headers = _auth(client, login, "planner")
    bootstrap = _bootstrap(client)
    assignments = client.get(f"/api/v1/assignments?shift_id={old_session['shift_id']}").json()["items"]
    source = next(item for item in assignments if item["id"] == old_session["assignment_id"])
    row = next(item for item in bootstrap["rows"] if item["category"] == "ASSEMBLY")
    station = next(item for item in bootstrap["workstations"] if item["row_id"] == row["id"])
    step = next(item for item in bootstrap["route_steps"] if "ASSEMBLE" in item["code"])
    moved = client.post(f"/api/v1/shifts/{old_session['shift_id']}/assignments", headers=planner_headers, json={
        "employee_id": source["employee_id"], "row_id": row["id"], "workstation_id": station["id"],
        "route_step_id": step["id"], "starts_at": "2026-10-25T09:00:00Z", "ends_at": "2026-10-25T13:00:00Z",
        "transfer_from_assignment_id": source["id"],
    })
    assert moved.status_code == 201, moved.text
    solder_headers = _auth(client, login, "solder")
    response = client.post("/api/v1/operation-events", headers=solder_headers, json={
        "event_id": str(uuid4()), "work_session_id": old_session["id"], "subject_qr": "DEMO-WIP-004",
        "event_type": "COMPLETE", "attempt_type": "PRIMARY", "attempt_no": 1,
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORK_ASSIGNMENT_INACTIVE"


def test_scan_is_blocked_after_scrap(client: TestClient, login) -> None:
    foreman_headers = _auth(client, login, "foreman")
    scrapped = client.post("/api/v1/genealogy/actions", headers=foreman_headers, json={
        "request_id": str(uuid4()), "action": "SCRAP", "parent_qr": "DEMO-WIP-004",
        "child_qr": "DEMO-WIP-005", "reason": "ДЕМО списание",
    })
    assert scrapped.status_code == 201, scrapped.text
    solder_headers = _auth(client, login, "solder")
    session = _work_session(client)
    response = client.post("/api/v1/operation-events", headers=solder_headers, json={
        "event_id": str(uuid4()), "work_session_id": session["id"], "subject_qr": "DEMO-WIP-005",
        "event_type": "COMPLETE", "attempt_type": "PRIMARY", "attempt_no": 1,
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ENTITY_NOT_SCANNABLE"
