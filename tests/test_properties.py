"""Property management API tests."""
from __future__ import annotations


async def _create(client, headers, **overrides):
    payload = {
        "name": "Sunset Villa",
        "description": "Beachfront getaway",
        "location_text": "Goa, India",
        "lat": 15.2993,
        "lng": 74.1240,
        "b2b_rate": "120.00",
        "b2c_rate": "180.00",
    }
    payload.update(overrides)
    return await client.post("/api/v1/properties", json=payload, headers=headers)


async def test_create_requires_manager(client, agent_headers):
    resp = await _create(client, agent_headers)
    assert resp.status_code == 403


async def test_create_and_list(client, manager_headers):
    a = await _create(client, manager_headers, name="A")
    b = await _create(client, manager_headers, name="B")
    assert a.status_code == 201
    assert b.status_code == 201

    lst = await client.get("/api/v1/properties", headers=manager_headers)
    assert lst.status_code == 200
    body = lst.json()
    assert body["total"] == 2
    assert body["limit"] == 20
    assert body["offset"] == 0
    names = sorted(p["name"] for p in body["items"])
    assert names == ["A", "B"]


async def test_list_pagination_and_status_filter(client, manager_headers):
    for i in range(3):
        await _create(client, manager_headers, name=f"P{i}")

    page1 = await client.get(
        "/api/v1/properties?limit=2&offset=0", headers=manager_headers
    )
    assert page1.status_code == 200
    assert len(page1.json()["items"]) == 2
    assert page1.json()["total"] == 3

    page2 = await client.get(
        "/api/v1/properties?limit=2&offset=2", headers=manager_headers
    )
    assert len(page2.json()["items"]) == 1

    # close one and filter
    created = await _create(client, manager_headers, name="ToClose")
    await client.post(
        f"/api/v1/properties/{created.json()['id']}/close", headers=manager_headers
    )
    booked = await client.get(
        "/api/v1/properties?status=booked", headers=manager_headers
    )
    assert booked.json()["total"] == 1
    assert booked.json()["items"][0]["name"] == "ToClose"


async def test_list_only_returns_own_properties(
    client, manager_headers, other_manager_headers
):
    await _create(client, manager_headers, name="Mine")
    await _create(client, other_manager_headers, name="Theirs")

    mine = await client.get("/api/v1/properties", headers=manager_headers)
    assert mine.json()["total"] == 1
    assert mine.json()["items"][0]["name"] == "Mine"


async def test_get_detail_includes_children(client, manager_headers):
    created = (await _create(client, manager_headers)).json()
    pid = created["id"]

    await client.post(
        f"/api/v1/properties/{pid}/rooms",
        json={"room_type": "Suite", "capacity": 2, "count": 4},
        headers=manager_headers,
    )
    await client.post(
        f"/api/v1/properties/{pid}/amenities",
        json={"name": "Pool", "icon_key": "pool"},
        headers=manager_headers,
    )

    detail = await client.get(f"/api/v1/properties/{pid}", headers=manager_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["rooms"]) == 1
    assert body["rooms"][0]["room_type"] == "Suite"
    assert len(body["amenities"]) == 1
    assert body["amenities"][0]["name"] == "Pool"
    assert body["photos"] == []


async def test_other_manager_cannot_access_property(
    client, manager_headers, other_manager_headers
):
    created = (await _create(client, manager_headers)).json()
    pid = created["id"]
    resp = await client.get(
        f"/api/v1/properties/{pid}", headers=other_manager_headers
    )
    assert resp.status_code == 403


async def test_patch_updates_fields(client, manager_headers):
    pid = (await _create(client, manager_headers)).json()["id"]
    resp = await client.patch(
        f"/api/v1/properties/{pid}",
        json={"name": "Renamed", "b2c_rate": "200.00"},
        headers=manager_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    assert resp.json()["b2c_rate"] == "200.00"


async def test_close_only_from_active(client, manager_headers):
    pid = (await _create(client, manager_headers)).json()["id"]
    first = await client.post(
        f"/api/v1/properties/{pid}/close", headers=manager_headers
    )
    assert first.status_code == 200
    assert first.json()["status"] == "booked"

    second = await client.post(
        f"/api/v1/properties/{pid}/close", headers=manager_headers
    )
    assert second.status_code == 400
    assert "status=booked" in second.json()["detail"]


async def test_delete_room_and_amenity(client, manager_headers):
    pid = (await _create(client, manager_headers)).json()["id"]
    room = await client.post(
        f"/api/v1/properties/{pid}/rooms",
        json={"room_type": "Standard", "capacity": 2, "count": 1},
        headers=manager_headers,
    )
    am = await client.post(
        f"/api/v1/properties/{pid}/amenities",
        json={"name": "Wifi"},
        headers=manager_headers,
    )

    rd = await client.delete(
        f"/api/v1/properties/{pid}/rooms/{room.json()['id']}",
        headers=manager_headers,
    )
    ad = await client.delete(
        f"/api/v1/properties/{pid}/amenities/{am.json()['id']}",
        headers=manager_headers,
    )
    assert rd.status_code == 204
    assert ad.status_code == 204

    detail = (
        await client.get(f"/api/v1/properties/{pid}", headers=manager_headers)
    ).json()
    assert detail["rooms"] == []
    assert detail["amenities"] == []


async def test_upload_photo_and_set_primary(client, manager_headers, storage):
    pid = (await _create(client, manager_headers)).json()["id"]

    fake_png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    files = {"file": ("a.png", fake_png, "image/png")}
    p1 = await client.post(
        f"/api/v1/properties/{pid}/photos", files=files, headers=manager_headers
    )
    assert p1.status_code == 201
    assert p1.json()["is_primary"] is True

    files2 = {"file": ("b.png", fake_png, "image/png")}
    p2 = await client.post(
        f"/api/v1/properties/{pid}/photos", files=files2, headers=manager_headers
    )
    assert p2.json()["is_primary"] is False
    assert len(storage.objects) == 2

    promote = await client.patch(
        f"/api/v1/properties/{pid}/photos/{p2.json()['id']}/primary",
        headers=manager_headers,
    )
    assert promote.json()["is_primary"] is True

    detail = await client.get(f"/api/v1/properties/{pid}", headers=manager_headers)
    photos = detail.json()["photos"]
    primaries = [p for p in photos if p["is_primary"]]
    assert len(primaries) == 1
    assert primaries[0]["id"] == p2.json()["id"]


async def test_upload_photo_rejects_oversize(client, manager_headers, monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "MAX_PHOTO_SIZE_BYTES", 50)
    pid = (await _create(client, manager_headers)).json()["id"]
    big = b"x" * 200
    resp = await client.post(
        f"/api/v1/properties/{pid}/photos",
        files={"file": ("big.png", big, "image/png")},
        headers=manager_headers,
    )
    assert resp.status_code == 413


async def test_upload_photo_rejects_bad_content_type(client, manager_headers):
    pid = (await _create(client, manager_headers)).json()["id"]
    resp = await client.post(
        f"/api/v1/properties/{pid}/photos",
        files={"file": ("foo.pdf", b"%PDF-1.4", "application/pdf")},
        headers=manager_headers,
    )
    assert resp.status_code == 400
    assert "unsupported content_type" in resp.json()["detail"]


async def test_delete_photo_promotes_next_to_primary(client, manager_headers):
    pid = (await _create(client, manager_headers)).json()["id"]
    fake = b"\x89PNG\r\n\x1a\n" + b"0" * 32

    primary = await client.post(
        f"/api/v1/properties/{pid}/photos",
        files={"file": ("a.png", fake, "image/png")},
        headers=manager_headers,
    )
    secondary = await client.post(
        f"/api/v1/properties/{pid}/photos",
        files={"file": ("b.png", fake, "image/png")},
        headers=manager_headers,
    )
    assert primary.json()["is_primary"] is True

    await client.delete(
        f"/api/v1/properties/{pid}/photos/{primary.json()['id']}",
        headers=manager_headers,
    )
    detail = await client.get(
        f"/api/v1/properties/{pid}", headers=manager_headers
    )
    photos = detail.json()["photos"]
    assert len(photos) == 1
    assert photos[0]["id"] == secondary.json()["id"]
    assert photos[0]["is_primary"] is True
