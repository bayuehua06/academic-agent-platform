"""鉴权相关 API 测试。"""


async def test_register_success(client):
    res = await client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "secret123",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert "id" in body
    assert "password_hash" not in body


async def test_register_duplicate_username(client, test_user):
    res = await client.post(
        "/api/auth/register",
        json={
            "username": test_user.username,
            "email": "other@example.com",
            "password": "secret123",
        },
    )
    assert res.status_code == 400


async def test_login_success(client, test_user):
    res = await client.post(
        "/api/auth/login",
        data={"username": "tester", "password": "secret123"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_with_email(client, test_user):
    res = await client.post(
        "/api/auth/login",
        data={"username": "tester@example.com", "password": "secret123"},
    )
    assert res.status_code == 200
    assert res.json()["access_token"]


async def test_login_wrong_password(client, test_user):
    res = await client.post(
        "/api/auth/login",
        data={"username": "tester", "password": "wrong"},
    )
    assert res.status_code == 401


async def test_me_requires_auth(client):
    res = await client.get("/api/auth/me")
    assert res.status_code == 401


async def test_me_success(auth_client, test_user):
    res = await auth_client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.json()["username"] == test_user.username
