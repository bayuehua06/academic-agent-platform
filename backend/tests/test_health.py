"""健康检查与 OpenAPI 冒烟。"""


async def test_health(client):
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"


async def test_openapi_available(client):
    res = await client.get("/openapi.json")
    assert res.status_code == 200
    paths = res.json()["paths"]
    assert "/api/auth/register" in paths
    assert "/api/projects" in paths
