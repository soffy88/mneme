import pytest
from httpx import AsyncClient, ASGITransport
from services.main import app

@pytest.fixture
async def api_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
async def test_auth_send_code(api_client):
    # 1. 正常发送
    payload = {"phone": "13800138000"}
    response = await api_client.post("/v1/auth/send-code", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    
    # 2. 格式错误
    payload = {"phone": "123"}
    response = await api_client.post("/v1/auth/send-code", json=payload)
    assert response.status_code == 422
