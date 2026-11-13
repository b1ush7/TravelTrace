from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PlanNotification, PlanVersion, Room, RoomTemplate

PASSWORD = "TravelTrace-test-123"


def account(client, username):
    assert client.post("/api/v1/auth/register", json={
        "username": username, "password": PASSWORD, "display_name": username}).status_code == 201
    login = client.post("/api/v1/auth/session", json={"username": username, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def setup_room(client):
    owner = account(client, "owner")
    room = client.post("/api/v1/rooms", headers=owner, json={
        "name": "红色西安", "destination": "西安", "start_date": "2026-12-05", "end_date": "2026-12-06",
        "theme_code": "red_tour"}).json()
    invite = client.post(f"/api/v1/rooms/{room['id']}/invitations", headers=owner, json={}).json()
    member = account(client, "bob")
    assert client.post("/api/v1/rooms/join", headers=member,
                       json={"invite_code": invite["invite_code"]}).status_code == 201
    return owner, member, room


def add_activity(client, headers, room_id, version, name, place, cost):
    response = client.post(f"/api/v1/rooms/{room_id}/activities", headers=headers, json={
        "name": name, "place_name": place, "duration_minutes": 90, "estimated_cost_cny": cost,
        "cost_scope": "per_person", "reservation_status": "confirmed", "expected_room_version": version})
    assert response.status_code == 201, response.text
    return response.json()


def build_and_publish(client, owner, member, room):
    version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    first = add_activity(client, owner, room["id"], version, "八路军办事处", "八路军西安办事处纪念馆", 0)
    second = add_activity(client, owner, room["id"], first["room_version"], "西安事变纪念馆",
                          "西安事变纪念馆（张学良公馆）", 20)
    current_version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    job = client.post(f"/api/v1/rooms/{room['id']}/plan-jobs", headers=owner, json={
        "expected_room_version": current_version,
        "activity_ids": [first["id"], second["id"]], "allow_split": False})
    assert job.status_code == 202, job.text
    job_data = job.json()
    assert job_data["status"] == "succeeded" and job_data["result_version_id"]
    version_id = job_data["result_version_id"]
    for headers in (owner, member):
        confirmed = client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/confirmation",
                                headers=headers, json={
                                    "expected_room_version": current_version,
                                    "expected_current_version_id": None,
                                    "decision": "approve"})
        assert confirmed.status_code == 200, confirmed.text
    published = client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/publish",
                            headers=owner, json={"expected_room_version": current_version,
                                                 "expected_current_version_id": None})
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    return version_id, published.json()


def test_full_plan_publish_reach_share_archive_flow(client):
    owner, member, room = setup_room(client)
    version_id, published = build_and_publish(client, owner, member, room)

    current = client.get(f"/api/v1/rooms/{room['id']}/trip-versions/current", headers=member)
    assert current.status_code == 200 and current.json()["id"] == version_id
    assert current.json()["card_summary"]["title"]

    next_step = client.get(f"/api/v1/rooms/{room['id']}/next-step", headers=member)
    assert next_step.status_code == 200, next_step.text
    assert next_step.json()["current_version_id"] == version_id
    assert next_step.json()["meeting_activity"]["kind"] == "meeting"
    assert next_step.json()["live"]["stage"] == "before"
    assert next_step.json()["theme"]["code"] == "red_tour"

    live = client.get(f"/api/v1/rooms/{room['id']}/live-state", headers=member)
    assert live.status_code == 200, live.text
    assert live.json()["stage"] == "before"
    assert live.json()["privacy"] == {"hide_members": True, "hide_budget": True}
    assert live.json()["version_id"] == version_id

    cards = client.get("/api/v1/me/travel-cards", headers=member)
    assert cards.status_code == 200, cards.text
    card = next(item for item in cards.json() if item["room_id"] == room["id"])
    assert card["current_version_id"] == version_id
    assert card["days_to_start"] == 22
    assert card["next_meeting"]["place_name"] == "西安"

    overview = client.get(f"/api/v1/rooms/{room['id']}/overview", headers=member)
    assert overview.status_code == 200, overview.text
    data = overview.json()
    assert data["current_version_id"] == version_id
    assert data["theme_code"] == "red_tour"
    assert data["conflict_summary"] == {"open": 0, "resolved": 0, "key_member_ids": []}
    assert data["live"]["stage"] == "before"
    assert data["schedule"]["time_zone"] == "Asia/Shanghai"

    notifications = client.get(f"/api/v1/rooms/{room['id']}/notifications", headers=member)
    assert notifications.status_code == 200 and len(notifications.json()) == 1
    notification = notifications.json()[0]
    assert notification["kind"] == "change_published" and notification["channel"] == "in_app"
    ack = client.post(f"/api/v1/rooms/{room['id']}/notifications/{notification['id']}/ack",
                      headers=member)
    assert ack.status_code == 200 and ack.json()["acked_at"]

    device = {"device_id": "device-1", "platform": "coloros",
              "capabilities": ["fluid_cloud", "card", "push"], "app_version": "0.6.0",
              "push_token": "push-token-1234567890"}
    first = client.post("/api/v1/devices/push-subscriptions", headers=member, json=device)
    second = client.post("/api/v1/devices/push-subscriptions", headers=member, json=device)
    assert first.status_code == 200 and first.json()["id"] == second.json()["id"]
    assert first.json()["push_token_masked"] == "push****7890"
    assert "push_token" not in first.json()
    assert client.delete(f"/api/v1/devices/push-subscriptions/{first.json()['id']}",
                         headers=member).status_code == 204
    assert client.delete(f"/api/v1/devices/push-subscriptions/{first.json()['id']}",
                         headers=member).status_code == 404

    share = client.post(f"/api/v1/rooms/{room['id']}/share-links", headers=owner, json={
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})
    assert share.status_code == 201, share.text
    token = share.json()["url"].rsplit("/", 1)[-1]
    shared = client.get(f"/api/v1/shared-plans/{token}")
    assert shared.status_code == 200, shared.text
    assert shared.json()["destination"] == "西安"
    assert shared.json()["theme"]["badge"] == "Demo 主题"
    assert "member_ids" not in shared.text and "budget" not in shared.text
    assert len(shared.json()["activities"]) >= 3
    assert client.delete(f"/api/v1/rooms/{room['id']}/share-links/{share.json()['id']}",
                         headers=owner).status_code == 204
    assert client.get(f"/api/v1/shared-plans/{token}").status_code == 404

    room_version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    archived = client.post(f"/api/v1/rooms/{room['id']}/archive", headers=owner,
                           json={"expected_room_version": room_version})
    assert archived.status_code == 200, archived.text
    assert archived.json()["version_id"] == version_id
    assert archived.json()["cost"]["estimated_cny"] >= 0
    retro = client.get(f"/api/v1/rooms/{room['id']}/retrospective", headers=member)
    assert retro.status_code == 200 and retro.json()["room_id"] == room["id"]
    assert client.post(f"/api/v1/rooms/{room['id']}/messages", headers=member,
                       json={"content": "after archive"}).status_code == 409

    templates = client.get("/api/v1/me/templates", headers=owner)
    assert templates.status_code == 200 and len(templates.json()) == 1
    template = templates.json()[0]
    assert template["destination"] == "西安" and template["theme_code"] == "red_tour"
    recreated = client.post("/api/v1/rooms/from-template", headers=owner, json={
        "template_id": template["id"], "name": "同款再出发",
        "start_date": "2027-01-10", "end_date": "2027-01-11"})
    assert recreated.status_code == 200, recreated.text
    new_room = recreated.json()
    assert new_room["destination"] == "西安" and new_room["theme_code"] == "red_tour"
    new_versions = client.get(f"/api/v1/rooms/{new_room['id']}/trip-versions", headers=owner).json()
    assert len(new_versions) == 1 and new_versions[0]["status"] == "awaiting_confirmation"
    assert len(new_versions[0]["activities"]) >= 2


def test_publish_requires_all_confirmations(client):
    owner, member, room = setup_room(client)
    version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    activity = add_activity(client, owner, room["id"], version, "革命公园", "革命公园", 0)
    current = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    version_id = client.post(f"/api/v1/rooms/{room['id']}/plan-jobs", headers=owner, json={
        "expected_room_version": current, "activity_ids": [activity["id"]]}).json()["result_version_id"]
    assert client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/publish",
                       headers=owner, json={"expected_room_version": current,
                                            "expected_current_version_id": None}).status_code == 409
    confirmed = client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/confirmation",
                            headers=owner, json={"expected_room_version": current,
                                                 "expected_current_version_id": None,
                                                 "decision": "approve"})
    assert confirmed.status_code == 200
    still_pending = client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/publish",
                                headers=owner, json={"expected_room_version": current,
                                                     "expected_current_version_id": None})
    assert still_pending.status_code == 409
    rejected = client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/confirmation",
                           headers=member, json={"expected_room_version": current,
                                                 "expected_current_version_id": None,
                                                 "decision": "reject", "comment": "时间太赶"})
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"


def test_job_query_validation_activity_update_refresh_cancel(client):
    owner, member, room = setup_room(client)
    version = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    activity = add_activity(client, owner, room["id"], version, "八路军办事处", "八路军西安办事处纪念馆", 0)
    current = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    updated = client.put(f"/api/v1/rooms/{room['id']}/activities/{activity['id']}", headers=owner, json={
        "name": "八路军办事处（更新）", "place_name": "八路军西安办事处纪念馆",
        "duration_minutes": 120, "estimated_cost_cny": 10, "cost_scope": "per_person",
        "reservation_status": "confirmed", "expected_room_version": current})
    assert updated.status_code == 200, updated.text
    assert updated.json()["duration_minutes"] == 120 and updated.json()["name"].endswith("（更新）")

    current = updated.json()["room_version"]
    job = client.post(f"/api/v1/rooms/{room['id']}/plan-jobs", headers=owner, json={
        "expected_room_version": current, "activity_ids": [activity["id"]]})
    assert job.status_code == 202, job.text
    job_data = job.json()
    assert job_data["status"] == "succeeded" and job_data["result_version_id"]

    fetched = client.get(f"/api/v1/rooms/{room['id']}/jobs/{job_data['id']}", headers=member)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["result_version_id"] == job_data["result_version_id"]
    assert client.delete(f"/api/v1/rooms/{room['id']}/jobs/{job_data['id']}",
                         headers=member).status_code == 409

    validation = client.get(
        f"/api/v1/rooms/{room['id']}/trip-versions/{job_data['result_version_id']}/validation",
        headers=member)
    assert validation.status_code == 200, validation.text
    assert validation.json()["outcome"] in {"feasible", "data_missing", "unknown"}

    current = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()["version"]
    cancelled = client.post(
        f"/api/v1/rooms/{room['id']}/trip-versions/{job_data['result_version_id']}/cancel",
        headers=owner, json={"expected_room_version": current, "expected_current_version_id": None})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    refreshed = client.post(f"/api/v1/rooms/{room['id']}/conflicts/refresh", headers=member,
                            json={"expected_room_version": current})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["room_version"] >= current
