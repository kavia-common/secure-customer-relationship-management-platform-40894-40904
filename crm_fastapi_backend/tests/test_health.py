def test_health(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json().get("status") in {"ok", "healthy", "Healthy"}
