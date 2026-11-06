"""Run with TRAVELTRACE_TEST_DATABASE_URL; fixtures isolate each test in a temporary database."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tests.api.test_accounts_rooms_messages import account, invitation, room


@pytest.fixture(autouse=True)
def mysql_only(client):
    if client.app.state.engine.dialect.name != "mysql":
        pytest.skip("MySQL required for row-lock concurrency checks")


def test_last_room_slot_cannot_be_taken_twice(client):
    owner = account(client, "owner")
    room_id = room(client, owner)
    code = invitation(client, owner, room_id)
    for index in range(4):
        headers = account(client, f"joined{index}")
        assert client.post("/api/v1/rooms/join", headers=headers, json={"invite_code": code}).status_code == 201
    contenders = [account(client, f"contender{index}") for index in range(2)]
    barrier = Barrier(2)

    def join(headers):
        barrier.wait(timeout=10)
        return client.post("/api/v1/rooms/join", headers=headers, json={"invite_code": code}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(join, contenders))
    assert sorted(codes) == [201, 409]
    assert len(client.get(f"/api/v1/rooms/{room_id}/members", headers=owner).json()) == 6
    assert client.get(f"/api/v1/rooms/{room_id}", headers=owner).json()["version"] == 6


def test_concurrent_repeat_join_is_idempotent(client):
    owner, guest = account(client, "owner"), account(client, "guest")
    room_id = room(client, owner)
    code = invitation(client, owner, room_id)
    barrier = Barrier(2)

    def join(_):
        barrier.wait(timeout=10)
        return client.post("/api/v1/rooms/join", headers=guest, json={"invite_code": code})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(join, range(2)))
    assert all(result.status_code == 201 for result in results)
    assert results[0].json()["id"] == results[1].json()["id"]
    assert client.get(f"/api/v1/rooms/{room_id}", headers=owner).json()["version"] == 2


def test_parallel_sends_can_all_be_read_by_cursor(client):
    owner = account(client, "owner")
    room_id = room(client, owner)
    barrier = Barrier(4)

    def send(index):
        barrier.wait(timeout=10)
        result = client.post(f"/api/v1/rooms/{room_id}/messages", headers=owner, json={"content": f"message-{index}"})
        assert result.status_code == 201
        return result.json()["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        sent_ids = set(pool.map(send, range(4)))
    received_ids = []
    cursor = 0
    while True:
        page = client.get(f"/api/v1/rooms/{room_id}/messages", params={"after": cursor, "limit": 1}, headers=owner).json()
        received_ids.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    assert len(received_ids) == len(set(received_ids)) == 4
    assert set(received_ids) == sent_ids
