"""Auth flow tests: happy path (agent + manager) and OTP expiry."""
import re

import pytest

from app.api.v1.auth import OAUTH_STATE_PREFIX
from app.services.google_oauth import GoogleUserInfo


async def _seed_oauth_state(fake_redis, *, role: str = "agent") -> str:
    state = "test-state-abc"
    await fake_redis.set(f"{OAUTH_STATE_PREFIX}{state}", role, ex=600)
    return state


def _extract_otp(email_sender) -> str:
    assert email_sender.sent, "no email was sent"
    body = email_sender.sent[-1]["body"]
    match = re.search(r"\b(\d{6})\b", body)
    assert match, f"no 6-digit code in body: {body!r}"
    return match.group(1)


async def test_google_login_redirects_to_google(client):
    resp = await client.get(
        "/api/v1/auth/google", params={"role": "agent"}, follow_redirects=False
    )
    assert resp.status_code in (302, 307)
    assert "accounts.google.com" in resp.headers["location"]


async def test_full_happy_path_agent(client, fake_redis, email_sender):
    state = await _seed_oauth_state(fake_redis, role="agent")

    cb = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": state},
    )
    assert cb.status_code == 200, cb.text
    body = cb.json()
    pre_auth_token = body["pre_auth_token"]
    assert body["user"]["email"] == "newuser@example.com"
    assert body["user"]["role"] == "agent"

    headers = {"Authorization": f"Bearer {pre_auth_token}"}
    send = await client.post("/api/v1/auth/otp/send", headers=headers)
    assert send.status_code == 200, send.text
    code = _extract_otp(email_sender)

    verify = await client.post(
        "/api/v1/auth/otp/verify",
        json={"code": code},
        headers=headers,
    )
    assert verify.status_code == 200, verify.text
    v = verify.json()
    assert v["access_token"]
    assert v["requires_phone_verification"] is False
    assert v["user"]["email"] == "newuser@example.com"

    full_headers = {"Authorization": f"Bearer {v['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=full_headers)
    assert me.status_code == 200
    assert me.json()["email"] == "newuser@example.com"


async def test_manager_phone_verification(client, fake_redis, email_sender, sms_sender):
    state = await _seed_oauth_state(fake_redis, role="manager")
    cb = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": state},
    )
    pre_auth_token = cb.json()["pre_auth_token"]
    pre_headers = {"Authorization": f"Bearer {pre_auth_token}"}

    await client.post("/api/v1/auth/otp/send", headers=pre_headers)
    code = _extract_otp(email_sender)
    verify = await client.post(
        "/api/v1/auth/otp/verify", json={"code": code}, headers=pre_headers
    )
    v = verify.json()
    assert v["requires_phone_verification"] is True
    full_headers = {"Authorization": f"Bearer {v['access_token']}"}

    phone_send = await client.post(
        "/api/v1/auth/phone/send",
        json={"phone": "+15555550199"},
        headers=full_headers,
    )
    assert phone_send.status_code == 200, phone_send.text
    assert sms_sender.sent, "no SMS sent"
    sms_match = re.search(r"\b(\d{6})\b", sms_sender.sent[-1]["body"])
    assert sms_match
    phone_code = sms_match.group(1)

    phone_verify = await client.post(
        "/api/v1/auth/phone/verify",
        json={"code": phone_code},
        headers=full_headers,
    )
    assert phone_verify.status_code == 200, phone_verify.text
    assert phone_verify.json()["phone_verified"] is True


async def test_otp_expiry(client, fake_redis, email_sender):
    state = await _seed_oauth_state(fake_redis, role="agent")
    cb = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": state},
    )
    pre_auth_token = cb.json()["pre_auth_token"]
    user_id = cb.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {pre_auth_token}"}

    await client.post("/api/v1/auth/otp/send", headers=headers)
    code = _extract_otp(email_sender)

    # Simulate TTL expiry by deleting the key (Redis would do this automatically
    # after OTP_TTL_SECONDS).
    deleted = await fake_redis.delete(f"otp:{user_id}")
    assert deleted == 1

    resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"code": code},
        headers=headers,
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


async def test_invalid_otp_rejected(client, fake_redis, email_sender):
    state = await _seed_oauth_state(fake_redis, role="agent")
    cb = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": state},
    )
    headers = {"Authorization": f"Bearer {cb.json()['pre_auth_token']}"}
    await client.post("/api/v1/auth/otp/send", headers=headers)
    _ = _extract_otp(email_sender)

    resp = await client.post(
        "/api/v1/auth/otp/verify", json={"code": "000000"}, headers=headers
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid otp"


async def test_full_token_cannot_call_pre_auth_routes(client, fake_redis, email_sender):
    state = await _seed_oauth_state(fake_redis, role="agent")
    cb = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": state},
    )
    pre_headers = {"Authorization": f"Bearer {cb.json()['pre_auth_token']}"}
    await client.post("/api/v1/auth/otp/send", headers=pre_headers)
    code = _extract_otp(email_sender)
    verify = await client.post(
        "/api/v1/auth/otp/verify", json={"code": code}, headers=pre_headers
    )
    full_token = verify.json()["access_token"]

    # full token should be rejected for /otp/send (pre-auth-only)
    resp = await client.post(
        "/api/v1/auth/otp/send",
        headers={"Authorization": f"Bearer {full_token}"},
    )
    assert resp.status_code == 401


async def test_agent_cannot_call_phone_endpoints(client, fake_redis, email_sender):
    state = await _seed_oauth_state(fake_redis, role="agent")
    cb = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": state},
    )
    headers = {"Authorization": f"Bearer {cb.json()['pre_auth_token']}"}
    await client.post("/api/v1/auth/otp/send", headers=headers)
    code = _extract_otp(email_sender)
    verify = await client.post(
        "/api/v1/auth/otp/verify", json={"code": code}, headers=headers
    )
    full_headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/auth/phone/send",
        json={"phone": "+15555550100"},
        headers=full_headers,
    )
    assert resp.status_code == 403
    assert "manager" in resp.json()["detail"]


async def test_callback_with_invalid_state_rejected(client, stub_google):
    resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": "never-stored"},
    )
    assert resp.status_code == 400
    assert "oauth state" in resp.json()["detail"]
