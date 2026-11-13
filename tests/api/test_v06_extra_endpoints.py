from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatImport, Room

PASSWORD = "TravelTrace-test-123"


def account(client, username):
    assert client.post("/api/v1/auth/register", json={
        "username": username, "password": PASSWORD, "display_name": username}).status_code == 201
    login = client.post("/api/v1/auth/session", json={"username": username, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def make_room(client, headers, members=1):
    room = client.post("/api/v1/rooms", headers=headers, json={
        "name": "测试房间", "destination": "西安", "start_date": "2026-12-05",
        "end_date": "2026-12-06", "theme_code": "red_tour"}).json()
    joined = []
    for index in range(members - 1):
        invite = client.post(f"/api/v1/rooms/{room['id']}/invitations", headers=headers, json={}).json()
        h = account(client, f"member{index}")
        assert client.post("/api/v1/rooms/join", headers=h,
                           json={"invite_code": invite["invite_code"]}).status_code == 201
        joined.append(h)
    return room, joined


def add_activity(client, headers, room_id, version, name):
    response = client.post(f"/api/v1/rooms/{room_id}/activities", headers=headers, json={
        "name": name, "place_name": name, "duration_minutes": 60, "estimated_cost_cny": 0,
        "cost_scope": "per_person", "expected_room_version": version})
    assert response.status_code == 201, response.text
    return response.json()


def publish_plan(client, owner, members, room):
    version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    activity = add_activity(client, owner, room["id"], version, "八路军办事处")
    current = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    job = client.post(f"/api/v1/rooms/{room['id']}/plan-jobs", headers=owner, json={
        "expected_room_version": current, "activity_ids": [activity["id"]]}).json()
    version_id = job["result_version_id"]
    for headers in [owner] + members:
        assert client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/confirmation",
                           headers=headers, json={"expected_room_version": current,
                                                  "expected_current_version_id": None,
                                                  "decision": "approve"}).status_code == 200
    published = client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/publish",
                            headers=owner, json={"expected_room_version": current,
                                                 "expected_current_version_id": None})
    assert published.status_code == 200, published.text
    return version_id, published.json()


def test_schedule_revoke_leave_and_public_catalog(client):
    owner = account(client, "owner")
    room, members = make_room(client, owner, 2)
    member = members[0]
    version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    schedule = client.put(f"/api/v1/rooms/{room['id']}/schedule", headers=owner, json={
        "starts_at": "2026-12-05T08:00:00+08:00", "ends_at": "2026-12-06T20:00:00+08:00",
        "time_zone": "Asia/Shanghai", "expected_room_version": version})
    assert schedule.status_code == 200, schedule.text
    assert schedule.json()["room_version"] == version + 1
    overview = client.get(f"/api/v1/rooms/{room['id']}/overview", headers=owner).json()
    assert overview["schedule"]["starts_at"].startswith("2026-12-05T00:00:00")
    assert overview["schedule"]["time_zone"] == "Asia/Shanghai"
    bad_tz = client.put(f"/api/v1/rooms/{room['id']}/schedule", headers=owner, json={
        "starts_at": "2026-12-05T08:00:00+08:00", "ends_at": "2026-12-06T20:00:00+08:00",
        "time_zone": "Mars/Olympus", "expected_room_version": schedule.json()["room_version"]})
    assert bad_tz.status_code == 422
    outside = client.put(f"/api/v1/rooms/{room['id']}/schedule", headers=owner, json={
        "starts_at": "2026-12-01T08:00:00+08:00", "ends_at": "2026-12-02T20:00:00+08:00",
        "time_zone": "Asia/Shanghai", "expected_room_version": schedule.json()["room_version"]})
    assert outside.status_code == 422

    invite = client.post(f"/api/v1/rooms/{room['id']}/invitations", headers=owner, json={}).json()
    revoked = client.delete(f"/api/v1/rooms/{room['id']}/invitations", headers=owner)
    assert revoked.status_code == 200 and revoked.json()["revoked_count"] >= 1
    late = account(client, "late")
    assert client.post("/api/v1/rooms/join", headers=late,
                       json={"invite_code": invite["invite_code"]}).status_code == 400

    assert client.delete(f"/api/v1/rooms/{room['id']}/members/me", headers=owner).status_code == 409
    left = client.delete(f"/api/v1/rooms/{room['id']}/members/me", headers=member)
    assert left.status_code == 200 and left.json()["left"] is True
    members_left = client.get(f"/api/v1/rooms/{room['id']}/members", headers=owner).json()
    assert len(members_left) == 1

    places = client.get("/api/v1/places?city=西安&keyword=纪念馆")
    assert places.status_code == 200 and len(places.json()) >= 2
    assert all(item["city"] == "西安" for item in places.json())
    knowledge = client.get("/api/v1/knowledge/search?city=西安&query=开放")
    assert knowledge.status_code == 200 and knowledge.json()
    assert all(hit["source_url"].startswith("https://") for hit in knowledge.json())


def test_deals_chat_imports_and_extraction_jobs(client):
    owner = account(client, "owner")
    room, _ = make_room(client, owner)
    deal = client.post(f"/api/v1/rooms/{room['id']}/deals", headers=owner, json={
        "title": "包车 7 座", "place_name": "西安北站", "price_cny": 600, "people_count": 6,
        "url": "https://example.com/deal"})
    assert deal.status_code == 201, deal.text
    assert deal.json()["source"] == "user" and deal.json()["verification_status"] == "unverified"
    assert len(client.get(f"/api/v1/rooms/{room['id']}/deals", headers=owner).json()) == 1

    denied = client.post(f"/api/v1/rooms/{room['id']}/chat-imports", headers=owner, json={
        "text": "secret", "consent_confirmed": False, "retention": "retain_until_deleted"})
    assert denied.status_code == 422
    retained = client.post(f"/api/v1/rooms/{room['id']}/chat-imports", headers=owner, json={
        "text": "我想去博物馆", "consent_confirmed": True, "retention": "retain_until_deleted"})
    assert retained.status_code == 202, retained.text
    assert retained.json()["raw_status"] == "retained"
    assert client.delete(f"/api/v1/rooms/{room['id']}/chat-imports/{retained.json()['import_id']}",
                         headers=owner).json() == {"deleted": True}
    discard = client.post(f"/api/v1/rooms/{room['id']}/chat-imports", headers=owner, json={
        "text": "预算 1000", "consent_confirmed": True, "retention": "discard_after_extraction"})
    assert discard.status_code == 202 and discard.json()["raw_status"] == "deleted"
    with Session(client.app.state.engine) as session:
        row = session.get(ChatImport, UUID(discard.json()["import_id"]))
        assert row.text == ""
    version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    job = client.post(f"/api/v1/rooms/{room['id']}/extraction-jobs", headers=owner, json={
        "expected_room_version": version})
    assert job.status_code == 202, job.text
    assert job.json()["kind"] == "extract" and job.json()["status"] == "succeeded"


def test_proposal_vote_conclusion_duplicate_and_no_consensus(client):
    owner = account(client, "owner")
    room, members = make_room(client, owner, 3)
    version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    created = client.post(f"/api/v1/rooms/{room['id']}/proposals", headers=owner, json={
        "title": "上午去哪", "options": [{"label": "博物馆"}, {"label": "老街"}],
        "expected_room_version": version})
    assert created.status_code == 201, created.text
    proposal = created.json()
    assert proposal["pending_member_ids"] and proposal["version"] == 1
    option_id = proposal["options"][0]["id"]
    for headers in [owner] + members:
        voted = client.put(f"/api/v1/rooms/{room['id']}/proposals/{proposal['id']}/vote", headers=headers,
                           json={"option_id": option_id, "expected_proposal_version": proposal["version"]})
        assert voted.status_code == 200, voted.text
        proposal["version"] = proposal["version"] + 1
    room_version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    decided = client.post(f"/api/v1/rooms/{room['id']}/proposals/{proposal['id']}/conclusion",
                          headers=owner, json={"expected_room_version": room_version,
                                               "expected_proposal_version": proposal["version"]})
    assert decided.status_code == 200, decided.text
    assert decided.json()["effect"] == "preference_recorded"
    repeated = client.post(f"/api/v1/rooms/{room['id']}/proposals/{proposal['id']}/conclusion",
                           headers=owner, json={"expected_room_version": room_version,
                                                "expected_proposal_version": proposal["version"]})
    assert repeated.status_code == 200 and repeated.json()["id"] == decided.json()["id"]
    assert len(client.get(f"/api/v1/rooms/{room['id']}/decisions", headers=owner).json()) == 1

    version2 = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    second = client.post(f"/api/v1/rooms/{room['id']}/proposals", headers=owner, json={
        "title": "晚上去哪", "options": [{"label": "夜市"}, {"label": "酒吧"}, {"label": "回酒店"}],
        "expected_room_version": version2}).json()
    for index, headers in enumerate([owner] + members):
        client.put(f"/api/v1/rooms/{room['id']}/proposals/{second['id']}/vote", headers=headers,
                   json={"option_id": second["options"][index % 3]["id"],
                         "expected_proposal_version": second["version"] + index})
    room_version2 = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    no_consensus = client.post(f"/api/v1/rooms/{room['id']}/proposals/{second['id']}/conclusion",
                               headers=owner, json={"expected_room_version": room_version2,
                                                    "expected_proposal_version": second["version"] + 3})
    assert no_consensus.status_code == 409 and no_consensus.json()["code"] == "NO_CONSENSUS"


def test_replan_and_execution(client):
    owner = account(client, "owner")
    room, members = make_room(client, owner, 2)
    member = members[0]
    version_id, published = publish_plan(client, owner, members, room)
    current = client.get(f"/api/v1/rooms/{room['id']}/trip-versions/current", headers=owner).json()
    activity = next(item for item in current["activities"] if item["kind"] == "activity")
    room_version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    job = client.post(f"/api/v1/rooms/{room['id']}/replan-jobs", headers=owner, json={
        "base_version_id": version_id, "expected_room_version": room_version,
        "operation": "skip", "target_activity_id": activity["id"]})
    assert job.status_code == 202, job.text
    assert job.json()["result_version_id"]
    new_version = client.get(f"/api/v1/rooms/{room['id']}/trip-versions/{job.json()['result_version_id']}",
                             headers=owner).json()
    assert new_version["status"] == "awaiting_confirmation"
    assert activity["id"] in new_version["impact"]["changed_activity_ids"]

    execution = client.put(
        f"/api/v1/rooms/{room['id']}/trip-versions/current/activities/{activity['id']}/execution",
        headers=member, json={"expected_current_version_id": version_id,
                              "expected_room_version": room_version, "state": "completed"})
    assert execution.status_code == 200, execution.text
    assert execution.json()["state"] == "completed"
    assert execution.json()["room_version"] == room_version + 1
    repeated = client.put(
        f"/api/v1/rooms/{room['id']}/trip-versions/current/activities/{activity['id']}/execution",
        headers=member, json={"expected_current_version_id": version_id,
                              "expected_room_version": room_version + 1, "state": "completed"})
    assert repeated.status_code == 200 and repeated.json()["room_version"] == room_version + 1
    refreshed = client.get(f"/api/v1/rooms/{room['id']}/trip-versions/current", headers=owner).json()
    assert next(item for item in refreshed["activities"] if item["id"] == activity["id"])["execution_state"] == "completed"