import pytest
from httpx import AsyncClient, ASGITransport
from services.main import app
from obase.db import SessionLocal
from services.models import User, GuardianConsent
from sqlalchemy import delete, select

@pytest.fixture
async def api_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
async def test_auth_full_flow(api_client):
    phone = "13912345678"
    
    # 清理旧数据
    async with SessionLocal() as session:
        stmt = select(User.id).where(User.phone == phone)
        user_ids = (await session.execute(stmt)).scalars().all()
        if user_ids:
            await session.execute(delete(GuardianConsent).where(GuardianConsent.student_id.in_(user_ids)))
        await session.execute(delete(User).where(User.phone == phone))
        await session.commit()
    
    # 1. 发送验证码
    res = await api_client.post("/v1/auth/send-code", json={"phone": phone})
    assert res.status_code == 200
    
    # 2. 注册学生 (>=14岁)
    reg_payload = {
        "phone": phone,
        "code": "123456",
        "name": "Test Student",
        "birth_date": "2000-01-01",
        "grade": "高三"
    }
    res = await api_client.post("/v1/auth/register/student", json=reg_payload)
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["user"]["name"] == "Test Student"
    token = data["token"]
    
    # 3. 获取我
    res = await api_client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["phone"] == phone
    
    # 4. 登录
    res = await api_client.post("/v1/auth/login", json={"phone": phone, "code": "123456"})
    assert res.status_code == 200
    assert "token" in res.json()

@pytest.mark.asyncio
async def test_auth_underage_compliance(api_client):
    phone = "13900001111"
    # 清理
    async with SessionLocal() as session:
        stmt = select(User.id).where(User.phone == phone)
        user_ids = (await session.execute(stmt)).scalars().all()
        if user_ids:
            await session.execute(delete(GuardianConsent).where(GuardianConsent.student_id.in_(user_ids)))
        await session.execute(delete(User).where(User.phone == phone))
        await session.commit()
        
    # <14岁注册，无监护人信息应失败
    reg_payload_fail = {
        "phone": phone,
        "code": "123456",
        "name": "Small Kid Fail",
        "birth_date": "2020-01-01",
        "grade": "三年级"
    }
    res = await api_client.post("/v1/auth/register/student", json=reg_payload_fail)
    assert res.status_code == 422
    assert "Guardian consent required" in res.json()["detail"]

    # <14岁注册，带监护人信息应成功
    reg_payload_ok = {
        "phone": phone,
        "code": "123456",
        "name": "Small Kid",
        "birth_date": "2020-01-01",
        "grade": "三年级",
        "guardian_phone": "13888888888",
        "guardian_consent": True
    }
    res = await api_client.post("/v1/auth/register/student", json=reg_payload_ok)
    assert res.status_code == 200
    
    # 验证数据库中是否有 GuardianConsent 记录
    async with SessionLocal() as session:
        stmt = select(GuardianConsent).where(GuardianConsent.guardian_phone == "13888888888")
        consent = (await session.execute(stmt)).scalar_one_or_none()
        assert consent is not None
        assert consent.consent_type == "registration"
