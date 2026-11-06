from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Invitation, Room, User, utcnow

PASSWORD = "TravelTrace-test-123"


def account(client, username):
    result = client.post("/api/v1/auth/register", json={"username": username, "password": PASSWORD, "display_name": username})
    assert result.status_code == 201, result.text
    login = client.post("/api/v1/auth/session", json={"username": username, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def room(client, headers):
    r = client.post("/api/v1/rooms", headers=headers, json={"name": "周末旅行", "destination": "长沙", "start_date": "2026-12-01", "end_date": "2026-12-02"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def invitation(client, headers, room_id):
    r = client.post(f"/api/v1/rooms/{room_id}/invitations", headers=headers, json={})
    assert r.status_code == 201, r.text
    return r.json()["invite_code"]


def test_register_login_hash_and_identity(client):
    headers = account(client, "Alice")
    result = client.get("/api/v1/me", headers=headers)
    assert result.json()["username"] == "alice"
    assert "password" not in result.text
    with Session(client.app.state.engine) as session:
        user = session.scalar(select(User))
        assert user.password_hash != PASSWORD and user.password_hash.startswith("$argon2")
    assert client.post("/api/v1/auth/register", json={"username":"ALICE", "password":PASSWORD,"display_name":"another"}).status_code == 409


def test_authentication_and_redacted_validation(client):
    account(client, "alice")
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization":"Bearer fake"}).status_code == 401
    for username in ("alice", "absent"):
        assert client.post("/api/v1/auth/session",json={"username":username,"password":"WrongPassword"}).status_code == 401
    r=client.post("/api/v1/auth/register",json={"username":"xy", "password":"sensitive","display_name":"name"})
    assert r.status_code == 422 and "sensitive" not in r.text
    assert r.json()["request_id"] == r.headers["x-request-id"]


def test_three_members_and_messages(client):
    a,b,c = [account(client, x) for x in ("alice","bobby","carol")]
    rid = room(client,a)
    code=invitation(client,a,rid)
    for headers in (b,c):
        assert client.post("/api/v1/rooms/join",headers=headers,json={"invite_code":code}).status_code==201
    assert len(client.get(f"/api/v1/rooms/{rid}/members",headers=a).json())==3
    assert client.get(f"/api/v1/rooms/{rid}",headers=b).json()["version"]==3
    for i,headers in enumerate((a,b,c)):
        assert client.post(f"/api/v1/rooms/{rid}/messages",headers=headers,json={"content":f"意见{i}"}).status_code==201
    page=client.get(f"/api/v1/rooms/{rid}/messages?limit=2",headers=c).json()
    assert len(page["items"])==2 and page["has_more"]
    final=client.get(f"/api/v1/rooms/{rid}/messages",params={"after":page["next_cursor"]},headers=c).json()
    assert len(final["items"])==1 and not final["has_more"]
    assert final["items"][0]["content"]=="意见2"
    assert client.get(f"/api/v1/rooms/{rid}",headers=a).json()["version"]==3


def test_outsider_permissions_and_room_list(client):
    a,b=account(client,"alice"),account(client,"bobby")
    rid=room(client,a)
    for suffix in ("", "/members", "/messages"):
        assert client.get(f"/api/v1/rooms/{rid}{suffix}",headers=b).status_code==403
    assert client.post(f"/api/v1/rooms/{rid}/messages",headers=b,json={"content":"intrusion"}).status_code==403
    assert client.get("/api/v1/rooms",headers=b).json()==[]
    assert len(client.get("/api/v1/rooms?limit=1",headers=a).json())==1


def test_expired_invalid_and_duplicate_invitation(client):
    a,b,c=[account(client,x) for x in ("alice","bobby","carol")]
    rid=room(client,a)
    code=invitation(client,a,rid)
    first=client.post("/api/v1/rooms/join",headers=b,json={"invite_code":code})
    second=client.post("/api/v1/rooms/join",headers=b,json={"invite_code":code})
    assert first.json()["id"]==second.json()["id"]
    assert client.get(f"/api/v1/rooms/{rid}",headers=a).json()["version"]==2
    assert client.post(f"/api/v1/rooms/{rid}/invitations",headers=b,json={}).status_code==403
    assert client.post("/api/v1/rooms/join",headers=c,json={"invite_code":"not-a-real-code"}).status_code==400
    with Session(client.app.state.engine) as session:
        inv=session.scalar(select(Invitation))
        assert inv.code_hash!=code
        inv.expires_at=utcnow()-timedelta(seconds=1)
        session.commit()
    assert client.post("/api/v1/rooms/join",headers=c,json={"invite_code":code}).status_code==400


def test_room_capacity(client):
    owner=account(client,"owner")
    rid=room(client,owner)
    code=invitation(client,owner,rid)
    for i in range(6):
        h=account(client,f"member{i}")
        r=client.post("/api/v1/rooms/join",headers=h,json={"invite_code":code})
        assert r.status_code==(201 if i<5 else 409)
    assert len(client.get(f"/api/v1/rooms/{rid}/members",headers=owner).json())==6


def test_validation_and_separate_room_message_cursors(client):
    a=account(client,"alice")
    rid=room(client,a)
    other=room(client,a)
    assert client.post(f"/api/v1/rooms/{rid}/messages",headers=a,json={"content":"  "}).status_code==422
    assert client.post(f"/api/v1/rooms/{rid}/messages",headers=a,json={"content":"x", "author_member_id":"spoof"}).status_code==422
    client.post(f"/api/v1/rooms/{other}/messages",headers=a,json={"content":"other room"})
    assert client.get(f"/api/v1/rooms/{rid}/messages",headers=a).json()["items"]==[]
    invalid=client.post("/api/v1/rooms",headers=a,json={"name":"trip","destination":"city","start_date":"2026-12-02","end_date":"2026-12-01"})
    assert invalid.status_code==422


def test_expired_token(client):
    import jwt
    from datetime import datetime, timezone
    headers=account(client,"alice")
    user_id=client.get("/api/v1/me",headers=headers).json()["id"]
    token=jwt.encode({"sub":user_id,"exp":datetime.now(timezone.utc)-timedelta(seconds=1),"iat":datetime.now(timezone.utc)-timedelta(hours=1),"aud":"traveltrace-api","iss":"traveltrace"},client.app.state.settings.jwt_secret.get_secret_value(),algorithm="HS256")
    assert client.get("/api/v1/me",headers={"Authorization":"Bearer "+token}).status_code==401
