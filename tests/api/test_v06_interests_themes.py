from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Member, PlanVersion, Room, utcnow

PASSWORD = "TravelTrace-test-123"


def account(client, username):
    assert client.post("/api/v1/auth/register", json={
        "username": username, "password": PASSWORD, "display_name": username}).status_code == 201
    login = client.post("/api/v1/auth/session", json={"username": username, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def make_room(client, headers, **extra):
    payload = {"name": "西安周末", "destination": "西安", "start_date": "2026-12-05", "end_date": "2026-12-06"}
    payload.update(extra)
    response = client.post("/api/v1/rooms", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def add_member(client, owner_headers, room_id, username):
    invite = client.post(f"/api/v1/rooms/{room_id}/invitations", headers=owner_headers, json={})
    assert invite.status_code == 201, invite.text
    headers = account(client, username)
    joined = client.post("/api/v1/rooms/join", headers=headers,
                         json={"invite_code": invite.json()["invite_code"]})
    assert joined.status_code == 201, joined.text
    return headers, joined.json()["id"]


def set_interests(client, headers, expected, items):
    return client.put("/api/v1/me/interests", headers=headers,
                      json={"expected_version": expected, "interests": items})


def test_tag_dictionary_is_public_and_cacheable(client):
    first = client.get("/api/v1/interests/tags")
    assert first.status_code == 200
    assert len(first.json()) >= 50
    assert first.headers["cache-control"].startswith("public")
    etag = first.headers["etag"]
    assert etag
    cached = client.get("/api/v1/interests/tags", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    red = client.get("/api/v1/interests/tags?domain=red").json()
    assert red and all(item["domain"] == "red" for item in red)
    assert client.get("/api/v1/interests/tags?domain=nope").status_code == 400


def test_interest_profile_replace_versioning_and_errors(client):
    headers = account(client, "alice")
    empty = client.get("/api/v1/me/interests", headers=headers).json()
    assert empty["interests"] == [] and empty["version"] == 0
    body = [
        {"tag_code": "red_history", "strength": 5, "role": "must", "visibility": "public", "source": "self"},
        {"tag_code": "hiking", "strength": 2, "role": "avoid", "visibility": "room", "source": "self"},
    ]
    saved = set_interests(client, headers, 0, body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert {item["tag_code"] for item in saved.json()["interests"]} == {"red_history", "hiking"}
    stale = set_interests(client, headers, 0, body)
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    assert set_interests(client, headers, 1, [
        {"tag_code": "not_a_tag", "strength": 1, "role": "want", "visibility": "public", "source": "self"}
    ]).json()["code"] == "TAG_UNKNOWN"
    too_many = [{"tag_code": "hiking", "strength": 1, "role": "want", "visibility": "public", "source": "self"}] * 31
    assert set_interests(client, headers, 1, too_many).status_code == 422
    stats = client.get("/api/v1/me/interests/stats", headers=headers).json()
    assert stats["total_tags"] == 2
    assert stats["top_tags"][0]["tag_code"] == "red_history"
    assert sum(item["count"] for item in stats["by_domain"]) == 2


def test_room_interest_aggregation_excludes_private_and_finds_clash(client):
    owner = account(client, "owner")
    room = make_room(client, owner)
    member, _ = add_member(client, owner, room["id"], "bob")
    assert set_interests(client, owner, 0, [
        {"tag_code": "red_history", "strength": 5, "role": "must", "visibility": "public", "source": "self"},
        {"tag_code": "coffee", "strength": 3, "role": "want", "visibility": "private", "source": "self"},
    ]).status_code == 200
    assert set_interests(client, member, 0, [
        {"tag_code": "red_history", "strength": 4, "role": "avoid", "visibility": "room", "source": "self"},
        {"tag_code": "hiking", "strength": 4, "role": "want", "visibility": "public", "source": "self"},
    ]).status_code == 200
    overview = client.get(f"/api/v1/rooms/{room['id']}/interests", headers=owner)
    assert overview.status_code == 200, overview.text
    data = overview.json()
    assert data["member_count"] == 2 and data["filled_member_count"] == 2
    assert data["coverage"] == 1.0
    assert data["private_excluded"] == 1
    assert data["common_tags"] == []
    assert data["clash_tags"][0]["tag_code"] == "red_history"
    assert len(data["clash_tags"][0]["must_member_ids"]) == 1
    assert len(data["clash_tags"][0]["avoid_member_ids"]) == 1
    room_detail = client.get(f"/api/v1/rooms/{room['id']}", headers=owner).json()
    assert room_detail["interest_summary"] == {"common_count": 0, "conflict_count": 1}


def test_theme_catalog_and_room_theme_lifecycle(client):
    owner = account(client, "owner")
    room = make_room(client, owner)
    themes = client.get("/api/v1/themes").json()
    assert any(item["code"] == "red_tour" and item["is_demo"] for item in themes)
    assert all(item["city_scope"] != "成都" for item in client.get("/api/v1/themes?city=西安").json())
    detail = client.get("/api/v1/themes/red_tour")
    assert detail.status_code == 200
    assert detail.json()["theme"]["fact_count"] >= 5
    assert all(fact["source"] and fact["observed_at"] for fact in detail.json()["facts"])
    packs = client.get("/api/v1/themes/red_tour/packs").json()
    assert {pack["days"] for pack in packs} == {2, 3}
    assert client.get("/api/v1/themes/nope").status_code == 404
    assert client.get("/api/v1/themes/nope/packs").status_code == 404

    updated = client.put(f"/api/v1/rooms/{room['id']}/theme", headers=owner,
                         json={"theme_code": "red_tour", "expected_room_version": room["version"]})
    assert updated.status_code == 200, updated.text
    assert updated.json()["theme_code"] == "red_tour"
    assert updated.json()["version"] == room["version"] + 1
    stale = client.put(f"/api/v1/rooms/{room['id']}/theme", headers=owner,
                       json={"theme_code": "red_tour", "expected_room_version": room["version"]})
    assert stale.status_code == 409

    with Session(client.app.state.engine) as session:
        member = session.scalar(select(Member).where(Member.room_id == UUID(room["id"])))
        session.add(PlanVersion(room_id=UUID(room["id"]), proposer_member_id=member.id,
                                input_room_version=updated.json()["version"], status="published",
                                published_at=utcnow()))
        session.commit()
    locked = client.put(f"/api/v1/rooms/{room['id']}/theme", headers=owner,
                        json={"theme_code": "city_walk_xian", "expected_room_version": updated.json()["version"]})
    assert locked.status_code == 409 and locked.json()["code"] == "THEME_LOCKED"


def test_create_room_validates_theme_and_city(client):
    owner = account(client, "owner")
    bad_city = client.post("/api/v1/rooms", headers=owner, json={
        "name": "成都", "destination": "成都", "start_date": "2026-12-01", "end_date": "2026-12-02",
        "theme_code": "red_tour"})
    assert bad_city.status_code == 422 and bad_city.json()["code"] == "THEME_CITY_MISMATCH"
    bad_tag = client.post("/api/v1/rooms", headers=owner, json={
        "name": "西安", "destination": "西安", "start_date": "2026-12-01", "end_date": "2026-12-02",
        "interest_tag_codes": ["nope"]})
    assert bad_tag.status_code == 422 and bad_tag.json()["code"] == "TAG_UNKNOWN"
    created = make_room(client, owner, theme_code="red_tour", interest_tag_codes=["red_history", "museum"])
    assert created["theme_code"] == "red_tour"
    overview = client.get(f"/api/v1/rooms/{created['id']}/interests", headers=owner).json()
    assert overview["filled_member_count"] == 1
    assert "red_history" in {tag["code"] for tag in overview["common_tags"]}
