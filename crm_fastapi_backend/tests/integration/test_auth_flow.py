import os
import uuid

import pytest


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")
def test_signup_login_logout_flow(client):
    email = f"u_{uuid.uuid4().hex[:8]}@example.com"
    password = "StrongPassw0rd!"
    # signup
    r = client.post("/auth/signup", json={"email": email, "password": password, "role": "agent"})
    assert r.status_code == 200, r.text
    user_id = r.json()["user_id"]
    assert user_id

    # login
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert token

    # me
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == email

    # logout
    r = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204
