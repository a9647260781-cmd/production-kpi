from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.models import OperationEvent, ProductionRow, RouteVersion, ShiftAssignment, TrackedEntity, User


def _auth(client: TestClient, login, username: str) -> dict[str, str]:
    user = login(client, username)
    return {"X-CSRF-Token": user["csrf_token"]}


def _row_ids(db: Session) -> dict[str, str]:
    return {row.code: row.id for row in db.scalars(select(ProductionRow))}


def _route_body(db: Session) -> dict:
    model_id = db.scalar(select(RouteVersion.model_id).order_by(RouteVersion.version))
    rows = _row_ids(db)
    return {
        "model_id": model_id,
        "steps": [
            {
                "code": "cfg-solder",
                "name": "ДЕМО пайка на новом маршруте",
                "sequence": 1,
                "entity_type": "WIP",
                "allowed_row_ids": [rows["DEMO-SOLDER-01"]],
                "allows_rework": True,
            },
            {
                "code": "cfg-build",
                "name": "ДЕМО альтернативная сборка",
                "sequence": 2,
                "entity_type": "WIP",
                "allowed_row_ids": [
                    rows["DEMO-ASM-01"],
                    rows["DEMO-ASM-02"],
                    rows["DEMO-ASM-03"],
                ],
                "allows_rework": True,
            },
            {
                "code": "cfg-qc",
                "name": "ДЕМО контроль",
                "sequence": 3,
                "entity_type": "WIP",
                "allowed_row_ids": [rows["DEMO-QC-01"]],
                "allows_rework": False,
            },
        ],
    }


def test_list_routes_expands_seed_assembly_alternatives(
    client: TestClient,
    login,
) -> None:
    _auth(client, login, "admin")
    response = client.get("/api/v1/route-versions")
    assert response.status_code == 200, response.text
    seed_route = next(item for item in response.json()["items"] if item["version"] == 1)
    assembly = next(step for step in seed_route["steps"] if "ASSEMBLE" in step["code"])
    assert seed_route["status"] == "APPROVED"
    assert seed_route["immutable"] is True
    assert assembly["row_scope"] == "ASSEMBLY_CATEGORY"
    assert {row["code"] for row in assembly["allowed_rows"]} == {
        "DEMO-ASM-01", "DEMO-ASM-02", "DEMO-ASM-03",
    }


def test_create_publish_route_and_create_wip_without_changing_existing_facts(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    original = seeded_db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-WIP-001"))
    assert original is not None
    original_route_id = original.route_version_id
    event_count = seeded_db.scalar(select(func.count()).select_from(OperationEvent))

    headers = _auth(client, login, "admin")
    created = client.post("/api/v1/route-versions", headers=headers, json=_route_body(seeded_db))
    assert created.status_code == 201, created.text
    route = created.json()
    assert route["version"] == 2
    assert route["status"] == "DRAFT"
    assert route["immutable"] is False
    assembly = route["steps"][1]
    assert assembly["row_scope"] == "ASSEMBLY_CATEGORY"
    assert len(assembly["allowed_rows"]) == 3

    rejected = client.post("/api/v1/tracked-entities", headers=headers, json={
        "qr_code": "CFG-WIP-DRAFT",
        "entity_type": "WIP",
        "route_version_id": route["id"],
    })
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "ROUTE_VERSION_NOT_PUBLISHED"

    published = client.post(f"/api/v1/route-versions/{route['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "APPROVED"
    assert published.json()["immutable"] is True

    entity = client.post("/api/v1/tracked-entities", headers=headers, json={
        "qr_code": "CFG-WIP-001",
        "entity_type": "WIP",
        "route_version_id": route["id"],
    })
    assert entity.status_code == 201, entity.text
    assert entity.json()["status"] == "IN_PROGRESS"
    assert entity.json()["route_version_id"] == route["id"]

    seeded_db.expire_all()
    unchanged = seeded_db.get(TrackedEntity, original.id)
    assert unchanged is not None
    assert unchanged.route_version_id == original_route_id
    assert seeded_db.scalar(select(func.count()).select_from(OperationEvent)) == event_count


def test_published_route_is_immutable(client: TestClient, seeded_db: Session, login) -> None:
    headers = _auth(client, login, "admin")
    created = client.post("/api/v1/route-versions", headers=headers, json=_route_body(seeded_db))
    route_id = created.json()["id"]
    assert client.post(f"/api/v1/route-versions/{route_id}/publish", headers=headers).status_code == 200
    repeated = client.post(f"/api/v1/route-versions/{route_id}/publish", headers=headers)
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "ROUTE_VERSION_IMMUTABLE"


def test_rejects_unrepresentable_subset_of_alternative_assembly_rows(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    headers = _auth(client, login, "admin")
    body = _route_body(seeded_db)
    body["steps"][1]["allowed_row_ids"] = body["steps"][1]["allowed_row_ids"][:2]
    response = client.post("/api/v1/route-versions", headers=headers, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ROUTE_ASSEMBLY_SUBSET_UNSUPPORTED"


def test_rejects_non_contiguous_sequence(client: TestClient, seeded_db: Session, login) -> None:
    headers = _auth(client, login, "admin")
    body = _route_body(seeded_db)
    body["steps"][2]["sequence"] = 4
    response = client.post("/api/v1/route-versions", headers=headers, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ROUTE_SEQUENCE_NOT_CONTIGUOUS"


def test_entity_qr_is_unique_and_component_uses_published_route(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    headers = _auth(client, login, "admin")
    route_id = seeded_db.scalar(
        select(RouteVersion.id)
        .where(RouteVersion.status == "APPROVED")
        .order_by(RouteVersion.version.desc())
    )
    body = {"qr_code": "CFG-COMP-001", "entity_type": "COMPONENT", "route_version_id": route_id}
    created = client.post("/api/v1/tracked-entities", headers=headers, json=body)
    assert created.status_code == 201, created.text
    assert created.json()["entity_type"] == "COMPONENT"
    assert created.json()["status"] == "ACTIVE"
    repeated = client.post("/api/v1/tracked-entities", headers=headers, json=body)
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "QR_ALREADY_EXISTS"


def test_create_final_entity_then_finalize_existing_wip(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    headers = _auth(client, login, "admin")
    route_id = seeded_db.scalar(select(RouteVersion.id).where(RouteVersion.status == "APPROVED"))
    created = client.post("/api/v1/tracked-entities", headers=headers, json={
        "qr_code": "CFG-FINAL-004",
        "entity_type": "FINAL",
        "route_version_id": route_id,
    })
    assert created.status_code == 201, created.text
    assert created.json()["entity_type"] == "FINAL"
    assert created.json()["final_serial"] == "CFG-FINAL-004"
    assert created.json()["status"] == "ACTIVE"

    finalized = client.post("/api/v1/genealogy/actions", headers=headers, json={
        "request_id": str(uuid4()),
        "action": "FINALIZE",
        "parent_qr": "CFG-FINAL-004",
        "child_qr": "DEMO-WIP-003",
        "reason": "ДЕМО выпуск нового маршрута",
    })
    assert finalized.status_code == 201, finalized.text
    assert finalized.json()["action"] == "FINALIZE"
    seeded_db.expire_all()
    wip = seeded_db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-WIP-003"))
    assert wip is not None and wip.status == "FINISHED"


def test_route_and_entity_mutations_enforce_capabilities(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    planner_headers = _auth(client, login, "planner")
    route_response = client.post("/api/v1/route-versions", headers=planner_headers, json=_route_body(seeded_db))
    assert route_response.status_code == 403
    assert route_response.json()["error"]["code"] == "CAPABILITY_REQUIRED"

    route_id = seeded_db.scalar(select(RouteVersion.id).where(RouteVersion.status == "APPROVED"))
    worker_headers = _auth(client, login, "assembly1")
    entity_response = client.post("/api/v1/tracked-entities", headers=worker_headers, json={
        "qr_code": "CFG-FORBIDDEN",
        "entity_type": "WIP",
        "route_version_id": route_id,
    })
    assert entity_response.status_code == 403
    assert entity_response.json()["error"]["code"] == "CAPABILITY_REQUIRED"


def test_tracked_entities_list_filters_by_route(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    _auth(client, login, "admin")
    route_id = seeded_db.scalar(select(RouteVersion.id).where(RouteVersion.status == "APPROVED"))
    response = client.get(f"/api/v1/tracked-entities?entity_type=WIP&route_version_id={route_id}")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 8
    assert all(item["entity_type"] == "WIP" for item in response.json()["items"])
    assert all(item["route_version_id"] == route_id for item in response.json()["items"])


def test_custom_route_arbitrary_step_code_can_be_assigned_and_scanned(
    client: TestClient,
    seeded_db: Session,
    login,
) -> None:
    rows = _row_ids(seeded_db)
    model_id = seeded_db.scalar(select(RouteVersion.model_id).order_by(RouteVersion.version))
    headers = _auth(client, login, "admin")
    route_response = client.post("/api/v1/route-versions", headers=headers, json={
        "model_id": model_id,
        "steps": [{
            "code": "CFG_BUILD",
            "name": "ДЕМО произвольный код сборки",
            "sequence": 1,
            "entity_type": "WIP",
            "allowed_row_ids": [rows["DEMO-ASM-01"], rows["DEMO-ASM-02"], rows["DEMO-ASM-03"]],
            "allows_rework": True,
        }],
    })
    assert route_response.status_code == 201, route_response.text
    route = route_response.json()
    assert client.post(f"/api/v1/route-versions/{route['id']}/publish", headers=headers).status_code == 200
    entity = client.post("/api/v1/tracked-entities", headers=headers, json={
        "qr_code": "CFG-WIP-SCAN-001",
        "entity_type": "WIP",
        "route_version_id": route["id"],
    })
    assert entity.status_code == 201, entity.text

    assembly_user = seeded_db.scalar(select(User).where(User.username == "assembly1"))
    assert assembly_user is not None
    old_assignment = seeded_db.scalar(
        select(ShiftAssignment).where(
            ShiftAssignment.employee_id == assembly_user.employee_id,
            ShiftAssignment.status == "ACTIVE",
        )
    )
    assert old_assignment is not None
    transfer_at = old_assignment.starts_at + timedelta(hours=4)
    assignment = client.post(
        f"/api/v1/shifts/{old_assignment.shift_id}/assignments",
        headers=headers,
        json={
            "employee_id": assembly_user.employee_id,
            "row_id": old_assignment.row_id,
            "workstation_id": old_assignment.workstation_id,
            "route_step_id": route["steps"][0]["id"],
            "starts_at": transfer_at.isoformat(),
            "ends_at": old_assignment.ends_at.isoformat(),
            "transfer_from_assignment_id": old_assignment.id,
        },
    )
    assert assignment.status_code == 201, assignment.text

    worker_headers = _auth(client, login, "assembly1")
    work_session = client.post("/api/v1/work-sessions", headers=worker_headers, json={
        "shift_id": old_assignment.shift_id,
        "row_id": old_assignment.row_id,
        "workstation_id": old_assignment.workstation_id,
        "route_step_id": route["steps"][0]["id"],
    })
    assert work_session.status_code == 201, work_session.text
    scanned = client.post("/api/v1/operation-events", headers=worker_headers, json={
        "event_id": str(uuid4()),
        "work_session_id": work_session.json()["id"],
        "subject_qr": "CFG-WIP-SCAN-001",
        "event_type": "COMPLETE",
        "attempt_type": "PRIMARY",
        "attempt_no": 1,
    })
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["accepted"] is True
    assert scanned.json()["code"] == "EVENT_ACCEPTED"
