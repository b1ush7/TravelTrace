"""End-to-end checks that the planner honours confirmed conditions.

The planner used to ignore claims and participation entirely, so these tests
assert on the generated plan rather than on the response envelope: activity
windows, member windows, reservations, cost scope and travel evidence must all
show up in the stored version.
"""

PASSWORD = "TravelTrace-test-123"


def account(client, username):
    assert client.post("/api/v1/auth/register", json={
        "username": username, "password": PASSWORD, "display_name": username}).status_code == 201
    login = client.post("/api/v1/auth/session", json={"username": username, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def setup_room(client, *, start="2026-12-05", end="2026-12-05"):
    owner = account(client, "owner")
    room = client.post("/api/v1/rooms", headers=owner, json={
        "name": "红色西安", "destination": "西安", "start_date": start, "end_date": end,
        "theme_code": "red_tour"}).json()
    invite = client.post(f"/api/v1/rooms/{room['id']}/invitations", headers=owner, json={}).json()
    member = account(client, "bob")
    assert client.post("/api/v1/rooms/join", headers=member,
                       json={"invite_code": invite["invite_code"]}).status_code == 201
    return owner, member, room


def room_version(client, headers, room_id):
    return client.get(f"/api/v1/rooms/{room_id}", headers=headers).json()["version"]


def add_activity(client, headers, room_id, version, **overrides):
    payload = {
        "name": "八路军办事处", "place_name": "八路军西安办事处纪念馆",
        "place_id": "xian-balu", "duration_minutes": 90, "estimated_cost_cny": 0,
        "cost_scope": "per_person", "reservation_status": "none",
        "expected_room_version": version,
    }
    payload.update(overrides)
    response = client.post(f"/api/v1/rooms/{room_id}/activities", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def set_participation(client, headers, room_id, version, *, joins_at, leaves_at, allow_solo=False):
    response = client.put(f"/api/v1/rooms/{room_id}/members/me/participation", headers=headers, json={
        "joins_at": joins_at, "leaves_at": leaves_at, "allow_solo": allow_solo,
        "expected_room_version": version})
    assert response.status_code == 200, response.text
    return response.json()


def confirm_claim(client, headers, room_id, **payload):
    """Create a hard claim for the caller and confirm it, as the contract requires."""
    body = {"field": "budget", "value": {"amount_cny": 500, "scope": "per_person"},
            "polarity": "unknown", "strength": "hard"}
    body.update(payload)
    created = client.post(f"/api/v1/rooms/{room_id}/claims", headers=headers, json=body)
    assert created.status_code == 201, created.text
    claim = created.json()
    confirmed = client.post(f"/api/v1/rooms/{room_id}/claims/{claim['id']}/decision",
                            headers=headers, json={"decision": "confirm",
                                                   "expected_version": claim["version"]})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def plan_job(client, headers, room_id, version, activity_ids, **extra):
    body = {"expected_room_version": version, "activity_ids": activity_ids}
    body.update(extra)
    response = client.post(f"/api/v1/rooms/{room_id}/plan-jobs", headers=headers, json=body)
    assert response.status_code == 202, response.text
    return response.json()


def stored_version(client, headers, room_id, version_id):
    fetched = client.get(f"/api/v1/rooms/{room_id}/trip-versions/{version_id}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    return fetched.json()


def member_rows(client, headers, room_id):
    return client.get(f"/api/v1/rooms/{room_id}", headers=headers).json()["members"]


def owner_member(client, headers, room_id):
    return next(item for item in member_rows(client, headers, room_id) if item["role"] == "owner")


def test_plan_places_activities_inside_their_windows(client):
    owner, member, room = setup_room(client, start="2026-12-05", end="2026-12-06")
    version = room_version(client, owner, room["id"])
    first = add_activity(client, owner, room["id"], version, name="上午馆",
                         window_start="2026-12-05T09:00:00+08:00",
                         window_end="2026-12-05T11:30:00+08:00")
    second = add_activity(client, owner, room["id"], first["room_version"], name="下午馆",
                          place_name="西安事变纪念馆（张学良公馆）", place_id="xian-incident",
                          window_start="2026-12-05T13:30:00+08:00",
                          window_end="2026-12-05T16:30:00+08:00")
    current = room_version(client, owner, room["id"])
    job = plan_job(client, owner, room["id"], current, [first["id"], second["id"]])
    assert job["status"] == "succeeded"

    stored = stored_version(client, owner, room["id"], job["result_version_id"])
    placed = [item for item in stored["activities"] if item["kind"] == "activity"]
    assert len(placed) == 2
    morning = next(item for item in placed if item["title"] == "上午馆")
    assert morning["starts_at"][11:16] == "09:00"
    assert morning["ends_at"][11:16] <= "11:30"
    afternoon = next(item for item in placed if item["title"] == "下午馆")
    assert afternoon["starts_at"][11:16] >= "13:30"


def test_plan_respects_confirmed_reservation(client):
    owner, member, room = setup_room(client)
    version = room_version(client, owner, room["id"])
    booked = add_activity(client, owner, room["id"], version, name="预约馆",
                          place_name="西安事变纪念馆（张学良公馆）", place_id="xian-incident",
                          reserved_start="2026-12-05T14:00:00+08:00",
                          reservation_status="confirmed")
    current = room_version(client, owner, room["id"])
    job = plan_job(client, owner, room["id"], current, [booked["id"]])

    stored = stored_version(client, owner, room["id"], job["result_version_id"])
    placed = next(item for item in stored["activities"] if item["title"] == "预约馆")
    assert placed["starts_at"][11:16] == "14:00"
    assert placed["commitment"] == "fixed"


def test_plan_cost_uses_scope_for_every_member(client):
    owner, member, room = setup_room(client)
    version = room_version(client, owner, room["id"])
    paid = add_activity(client, owner, room["id"], version, name="门票馆",
                        estimated_cost_cny=60, cost_scope="per_person")
    current = room_version(client, owner, room["id"])
    job = plan_job(client, owner, room["id"], current, [paid["id"]])

    stored = stored_version(client, owner, room["id"], job["result_version_id"])
    placed = next(item for item in stored["activities"] if item["kind"] == "activity")
    people = len(placed["member_ids"])
    assert people == 2
    # per_person 60 for two members is 120 in total, not 60.
    assert stored["estimated_cost_cny"] == 60 * people
    assert len(stored["member_budgets"]) == people
    for row in stored["member_budgets"]:
        assert row["estimated_cny"] == 60.0


def test_plan_connections_carry_distance_based_travel(client):
    owner, member, room = setup_room(client)
    version = room_version(client, owner, room["id"])
    first = add_activity(client, owner, room["id"], version, name="馆一",
                         place_name="八路军西安办事处纪念馆", place_id="xian-balu",
                         window_start="2026-12-05T09:00:00+08:00",
                         window_end="2026-12-05T11:00:00+08:00")
    second = add_activity(client, owner, room["id"], first["room_version"], name="馆二",
                          place_name="陕西历史博物馆", place_id="xian-museum",
                          window_start="2026-12-05T13:00:00+08:00",
                          window_end="2026-12-05T16:00:00+08:00")
    current = room_version(client, owner, room["id"])
    job = plan_job(client, owner, room["id"], current, [first["id"], second["id"]])

    stored = stored_version(client, owner, room["id"], job["result_version_id"])
    travels = [row for row in stored["connections"] if row["kind"] == "travel"]
    assert travels
    # The leg out of the synthetic meeting point has no coordinates, so only
    # the inter-activity legs must carry a distance-based estimate.
    placed_ids = {item["id"] for item in stored["activities"] if item["kind"] == "activity"}
    inter_activity = [row for row in travels if row["from_id"] in placed_ids]
    assert inter_activity, "two placed activities should produce one travel leg"
    for row in inter_activity:
        assert row["travel_minutes"] is not None
        assert row["source"] == "haversine_estimate"
        assert row["travel_minutes"] > 8


def test_plan_flags_unknown_travel_without_coordinates(client):
    owner, member, room = setup_room(client)
    version = room_version(client, owner, room["id"])
    first = add_activity(client, owner, room["id"], version, name="未知点一",
                         place_name="无坐标地点甲", place_id=None,
                         window_start="2026-12-05T09:00:00+08:00",
                         window_end="2026-12-05T11:00:00+08:00")
    second = add_activity(client, owner, room["id"], first["room_version"], name="未知点二",
                          place_name="无坐标地点乙", place_id=None,
                          window_start="2026-12-05T13:00:00+08:00",
                          window_end="2026-12-05T16:00:00+08:00")
    current = room_version(client, owner, room["id"])
    job = plan_job(client, owner, room["id"], current, [first["id"], second["id"]])

    stored = stored_version(client, owner, room["id"], job["result_version_id"])
    travels = [row for row in stored["connections"] if row["kind"] == "travel"]
    unknown = [row for row in travels if row["travel_minutes"] is None]
    assert unknown, "travel times should be unknown without coordinates"
    assert all(row["source"] == "unknown" for row in unknown)

    validation = client.get(
        f"/api/v1/rooms/{room['id']}/trip-versions/{job['result_version_id']}/validation",
        headers=member)
    assert validation.status_code == 200, validation.text
    codes = {issue["code"] for issue in validation.json()["issues"]}
    assert "TRAVEL_TIME_UNKNOWN" in codes


def test_plan_reports_missing_participation_as_unknown(client):
    owner, member, room = setup_room(client)
    version = room_version(client, owner, room["id"])
    activity = add_activity(client, owner, room["id"], version, name="默认馆")
    current = room_version(client, owner, room["id"])
    job = plan_job(client, owner, room["id"], current, [activity["id"]])

    stored = stored_version(client, owner, room["id"], job["result_version_id"])
    assert any("参与区间未填写" in note for note in stored["unknowns"])

    validation = client.get(
        f"/api/v1/rooms/{room['id']}/trip-versions/{job['result_version_id']}/validation",
        headers=member)
    codes = {issue["code"] for issue in validation.json()["issues"]}
    assert "PARTICIPATION_MISSING" in codes


def test_budget_claim_is_narrowed_and_reported(client):
    owner, member, room = setup_room(client)
    version = room_version(client, owner, room["id"])
    expensive = add_activity(client, owner, room["id"], version, name="昂贵馆",
                             estimated_cost_cny=900, cost_scope="per_person")
    confirm_claim(client, owner, room["id"], field="budget",
                  value={"amount_cny": 100, "scope": "per_person"}, strength="hard")
    current = room_version(client, owner, room["id"])
    job = plan_job(client, owner, room["id"], current, [expensive["id"]])

    validation = client.get(
        f"/api/v1/rooms/{room['id']}/trip-versions/{job['result_version_id']}/validation",
        headers=member)
    assert validation.status_code == 200, validation.text
    body = validation.json()
    codes = {issue["code"] for issue in body["issues"]}
    assert "BUDGET_EXCEEDED" in codes
    assert body["outcome"] == "infeasible"


def test_publish_is_blocked_by_budget_infeasibility(client):
    owner, member, room = setup_room(client)
    version = room_version(client, owner, room["id"])
    expensive = add_activity(client, owner, room["id"], version, name="昂贵馆",
                             estimated_cost_cny=900, cost_scope="per_person")
    confirm_claim(client, owner, room["id"], field="budget",
                  value={"amount_cny": 100, "scope": "per_person"}, strength="hard")
    current = room_version(client, owner, room["id"])
    job = plan_job(client, owner, room["id"], current, [expensive["id"]])
    version_id = job["result_version_id"]

    for headers in (owner, member):
        confirmed = client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/confirmation",
                                headers=headers, json={
                                    "expected_room_version": current,
                                    "expected_current_version_id": None,
                                    "decision": "approve"})
        assert confirmed.status_code == 200, confirmed.text

    blocked = client.post(f"/api/v1/rooms/{room['id']}/trip-versions/{version_id}/publish",
                          headers=owner, json={"expected_room_version": current,
                                               "expected_current_version_id": None})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "PLAN_INFEASIBLE"
