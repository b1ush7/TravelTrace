from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conflict, PlanVersion

PASSWORD = "TravelTrace-test-123"


def account(client, username):
    assert client.post("/api/v1/auth/register", json={
        "username": username, "password": PASSWORD, "display_name": username}).status_code == 201
    login = client.post("/api/v1/auth/session", json={"username": username, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def make_room(client, headers, destination="西安"):
    response = client.post("/api/v1/rooms", headers=headers, json={
        "name": "周末", "destination": destination, "start_date": "2026-12-05", "end_date": "2026-12-06"})
    assert response.status_code == 201, response.text
    return response.json()


def add_member(client, owner_headers, room_id, username):
    invite = client.post(f"/api/v1/rooms/{room_id}/invitations", headers=owner_headers, json={})
    headers = account(client, username)
    joined = client.post("/api/v1/rooms/join", headers=headers,
                         json={"invite_code": invite.json()["invite_code"]})
    assert joined.status_code == 201, joined.text
    return headers, joined.json()["id"]


def claim(client, headers, room_id, field, value, polarity="positive", strength="hard"):
    created = client.post(f"/api/v1/rooms/{room_id}/claims", headers=headers,
                          json={"field": field, "value": value, "polarity": polarity, "strength": strength})
    assert created.status_code == 201, created.text
    body = created.json()
    decided = client.post(f"/api/v1/rooms/{room_id}/claims/{body['id']}/decision", headers=headers,
                          json={"decision": "confirm", "expected_version": body["version"]})
    assert decided.status_code == 200, decided.text
    return decided.json()


def test_claims_lifecycle_and_permissions(client):
    owner = account(client, "owner")
    room = make_room(client, owner)
    member, member_id = add_member(client, owner, room["id"], "bob")
    created = client.post(f"/api/v1/rooms/{room['id']}/claims", headers=member, json={
        "field": "budget", "value": {"amount_cny": 800, "scope": "per_person"},
        "polarity": "positive", "strength": "hard"})
    assert created.status_code == 201, created.text
    claim_id = created.json()["id"]
    assert created.json()["status"] == "pending"
    owner_view = client.get(f"/api/v1/rooms/{room['id']}/claims", headers=owner).json()
    assert owner_view[0]["field"] == "budget"
    forbidden = client.patch(f"/api/v1/rooms/{room['id']}/claims/{claim_id}", headers=owner,
                             json={"strength": "soft", "expected_version": 1})
    assert forbidden.status_code == 403
    patched = client.patch(f"/api/v1/rooms/{room['id']}/claims/{claim_id}", headers=member,
                           json={"value": {"amount_cny": 600, "scope": "per_person"}, "expected_version": 1})
    assert patched.status_code == 200 and patched.json()["version"] == 2
    stale = client.patch(f"/api/v1/rooms/{room['id']}/claims/{claim_id}", headers=member,
                         json={"strength": "soft", "expected_version": 1})
    assert stale.status_code == 409
    confirmed = client.post(f"/api/v1/rooms/{room['id']}/claims/{claim_id}/decision", headers=member,
                            json={"decision": "confirm", "expected_version": 2})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"


def test_budget_conflict_relax_applies_immediately(client):
    owner = account(client, "owner")
    room = make_room(client, owner)
    member, member_id = add_member(client, owner, room["id"], "bob")
    claim(client, owner, room["id"], "budget", {"amount_cny": 1000, "scope": "per_person"})
    claim(client, member, room["id"], "budget", {"amount_cny": 500, "scope": "per_person"})
    conflicts = client.get(f"/api/v1/rooms/{room['id']}/conflicts", headers=owner)
    assert conflicts.status_code == 200, conflicts.text
    budget = [row for row in conflicts.json() if row["type"] == "budget"]
    assert budget and budget[0]["severity"] == "medium"
    assert budget[0]["resolution_count"] >= 5
    assert {"id", "type", "description", "status", "severity", "key_member_ids",
            "resolution_count"} <= set(budget[0])
    assert "code" not in budget[0] and "adjustment_options" not in budget[0]
    options = client.get(f"/api/v1/rooms/{room['id']}/conflicts/{budget[0]['id']}/resolutions",
                         headers=owner).json()
    assert options["room_version"] == client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    relax = next(option for option in options["options"] if option["action"] == "relax")
    assert relax["required_member_ids"] == [member_id]
    applied = client.post(f"/api/v1/rooms/{room['id']}/conflicts/{budget[0]['id']}/resolve",
                          headers=member, json={"option_id": relax["id"],
                                                "expected_room_version": options["room_version"]})
    assert applied.status_code == 200, applied.text
    assert applied.json()["effect"] == "applied"
    assert applied.json()["version_id"] is None
    assert applied.json()["room_version"] == options["room_version"] + 1
    after = client.get(f"/api/v1/rooms/{room['id']}/conflicts", headers=member).json()
    assert next(row for row in after if row["id"] == budget[0]["id"])["status"] == "resolved"


def test_place_conflict_pending_confirmation_creates_version(client):
    owner = account(client, "owner")
    room = make_room(client, owner)
    member, member_id = add_member(client, owner, room["id"], "bob")
    claim(client, owner, room["id"], "place", {"place_name": "陕西历史博物馆"}, "positive")
    claim(client, member, room["id"], "place", {"place_name": "陕西历史博物馆"}, "negative")
    conflicts = client.get(f"/api/v1/rooms/{room['id']}/conflicts", headers=owner).json()
    place = next(row for row in conflicts if row["type"] == "place")
    options = client.get(f"/api/v1/rooms/{room['id']}/conflicts/{place['id']}/resolutions",
                         headers=owner).json()
    replace = next(option for option in options["options"] if option["action"] == "replace")
    version_before = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    result = client.post(f"/api/v1/rooms/{room['id']}/conflicts/{place['id']}/resolve", headers=owner,
                         json={"option_id": replace["id"], "expected_room_version": version_before,
                               "comment": "先换一个点"})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["effect"] == "pending_confirmation"
    assert data["version_id"] and data["pending_member_ids"]
    assert data["room_version"] == version_before
    with Session(client.app.state.engine) as session:
        version = session.get(PlanVersion, UUID(data["version_id"]))
        assert version.status == "awaiting_confirmation"
        assert version.input_room_version == version_before
        assert version.impact["required_member_ids"] == data["pending_member_ids"]


def test_participation_and_version_conflict(client):
    owner = account(client, "owner")
    room = make_room(client, owner)
    body = {"joins_at": "2026-12-05T09:00:00+08:00", "leaves_at": "2026-12-05T18:00:00+08:00",
            "allow_solo": True, "expected_room_version": room["version"]}
    first = client.put(f"/api/v1/rooms/{room['id']}/members/me/participation", headers=owner, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["room_version"] == room["version"] + 1
    stale = client.put(f"/api/v1/rooms/{room['id']}/members/me/participation", headers=owner, json=body)
    assert stale.status_code == 409
    body["expected_room_version"] = first.json()["room_version"]
    second = client.put(f"/api/v1/rooms/{room['id']}/members/me/participation", headers=owner, json=body)
    assert second.status_code == 200 and second.json()["room_version"] == room["version"] + 2


def add_activity(client, headers, room_id, expected_room_version):
    created = client.post(f"/api/v1/rooms/{room_id}/activities", headers=headers, json={
        "name": "陕西历史博物馆", "place_name": "陕西历史博物馆", "duration_minutes": 120,
        "estimated_cost_cny": 0, "cost_scope": "per_person", "reservation_status": "confirmed",
        "expected_room_version": expected_room_version})
    assert created.status_code == 201, created.text
    return created.json()


def plan_and_approve(client, owner, member, room):
    room_version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    activity = add_activity(client, owner, room["id"], room_version)
    current = activity["room_version"]
    job = client.post(f"/api/v1/rooms/{room['id']}/plan-jobs", headers=owner, json={
        "expected_room_version": current, "activity_ids": [activity["id"]]})
    assert job.status_code == 202, job.text
    version_id = job.json()["result_version_id"]
    assert version_id
    for headers in (owner, member):
        confirmed = client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/confirmation",
                                headers=headers, json={
                                    "expected_room_version": current,
                                    "expected_current_version_id": None,
                                    "decision": "approve"})
        assert confirmed.status_code == 200, confirmed.text
    return version_id, current


def publish(client, owner, room, version_id, room_version):
    return client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/publish",
                       headers=owner, json={"expected_room_version": room_version,
                                            "expected_current_version_id": None})


def test_high_conflict_blocks_publish_even_after_confirmations(client):
    owner = account(client, "owner")
    room = make_room(client, owner)
    member, _ = add_member(client, owner, room["id"], "bob")
    claim(client, owner, room["id"], "budget", {"amount_cny": 1200, "scope": "per_person"})
    claim(client, member, room["id"], "budget", {"amount_cny": 400, "scope": "per_person"})
    conflicts = client.get(f"/api/v1/rooms/{room['id']}/conflicts", headers=owner)
    assert conflicts.status_code == 200, conflicts.text
    budget = next(row for row in conflicts.json() if row["type"] == "budget")
    assert budget["severity"] == "high"

    version_id, current = plan_and_approve(client, owner, member, room)
    blocked = publish(client, owner, room, version_id, current)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "PLAN_INFEASIBLE"
    assert "高优先级冲突" in blocked.json()["message"]
    detail = client.get(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}", headers=owner)
    assert detail.json()["status"] == "awaiting_confirmation"


def test_medium_conflict_does_not_block_publish(client):
    owner = account(client, "owner")
    room = make_room(client, owner)
    member, _ = add_member(client, owner, room["id"], "bob")
    claim(client, owner, room["id"], "budget", {"amount_cny": 1000, "scope": "per_person"})
    claim(client, member, room["id"], "budget", {"amount_cny": 600, "scope": "per_person"})
    conflicts = client.get(f"/api/v1/rooms/{room['id']}/conflicts", headers=owner).json()
    budget = next(row for row in conflicts if row["type"] == "budget")
    assert budget["severity"] == "medium"

    version_id, current = plan_and_approve(client, owner, member, room)
    published = publish(client, owner, room, version_id, current)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"


def test_theme_conflict_severity_stays_in_public_contract(client):
    owner = account(client, "owner")
    room = client.post("/api/v1/rooms", headers=owner, json={
        "name": "周一西安", "destination": "西安", "start_date": "2026-12-07",
        "end_date": "2026-12-08", "theme_code": "red_tour"}).json()
    refreshed = client.post(f"/api/v1/rooms/{room['id']}/conflicts/refresh", headers=owner,
                            json={"expected_room_version": room["version"]})
    assert refreshed.status_code == 200, refreshed.text
    theme = next(row for row in refreshed.json()["conflicts"] if "周一" in row["description"])
    assert theme["severity"] == "high"
    assert refreshed.json()["issues"][0]["severity"] in {"error", "warning", "unknown"}
