"""Tests for property-type catalog, privacy-type catalog, and super-admin
field-visibility controls.
"""
from __future__ import annotations


async def test_property_types_catalog(client):
    resp = await client.get("/api/v1/property-types")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 30  # full Airbnb-style catalog
    values = {entry["value"] for entry in body}
    assert {"house", "flat_apartment", "castle", "tree_house", "yurt"} <= values
    for entry in body:
        assert {"value", "label", "icon_key"} <= entry.keys()


async def test_privacy_types_catalog(client):
    resp = await client.get("/api/v1/privacy-types")
    assert resp.status_code == 200
    values = {e["value"] for e in resp.json()}
    assert values == {"entire_place", "a_room", "shared_room_hostel"}


async def test_create_property_with_full_basics(client, manager_headers):
    payload = {
        "name": "Cascade Villa",
        "b2b_rate": "120.00",
        "b2c_rate": "180.00",
        "property_type": "house",
        "privacy_type": "entire_place",
        "guests": 10,
        "bedrooms": 4,
        "beds": 6,
        "bathrooms": 3,
        "min_guests": 2,
        "max_guests": 12,
    }
    resp = await client.post(
        "/api/v1/properties", json=payload, headers=manager_headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["property_type"] == "house"
    assert body["privacy_type"] == "entire_place"
    assert body["guests"] == 10
    assert body["min_guests"] == 2
    assert body["max_guests"] == 12


async def test_min_guests_cannot_exceed_max(client, manager_headers):
    resp = await client.post(
        "/api/v1/properties",
        json={
            "name": "Bad",
            "b2b_rate": "10",
            "b2c_rate": "10",
            "min_guests": 10,
            "max_guests": 4,
        },
        headers=manager_headers,
    )
    assert resp.status_code == 422


async def test_list_field_configs_seeds_defaults(client, manager_headers):
    resp = await client.get(
        "/api/v1/admin/field-configs/property", headers=manager_headers
    )
    assert resp.status_code == 200
    rows = resp.json()
    names = {r["field_name"] for r in rows}
    assert "property_type" in names
    assert "min_guests" in names
    assert all(r["visible"] for r in rows)


async def test_manager_cannot_update_field_config(client, manager_headers):
    resp = await client.patch(
        "/api/v1/admin/field-configs/property/property_type",
        json={"visible": False},
        headers=manager_headers,
    )
    assert resp.status_code == 403


async def test_super_admin_disables_field(
    client, super_admin_headers, manager_headers
):
    # disable property_type
    upd = await client.patch(
        "/api/v1/admin/field-configs/property/property_type",
        json={"visible": False},
        headers=super_admin_headers,
    )
    assert upd.status_code == 200
    assert upd.json()["visible"] is False

    # manager can no longer set property_type
    create = await client.post(
        "/api/v1/properties",
        json={
            "name": "Test",
            "b2b_rate": "10",
            "b2c_rate": "10",
            "property_type": "house",
        },
        headers=manager_headers,
    )
    assert create.status_code == 422
    detail = create.json()["detail"]
    assert detail["fields"] == ["property_type"]

    # but creating WITHOUT property_type still works
    create2 = await client.post(
        "/api/v1/properties",
        json={"name": "Test", "b2b_rate": "10", "b2c_rate": "10"},
        headers=manager_headers,
    )
    assert create2.status_code == 201


async def test_super_admin_can_reenable_field(client, super_admin_headers, manager_headers):
    await client.patch(
        "/api/v1/admin/field-configs/property/lat",
        json={"visible": False},
        headers=super_admin_headers,
    )
    blocked = await client.post(
        "/api/v1/properties",
        json={"name": "T", "b2b_rate": "1", "b2c_rate": "1", "lat": 12.34},
        headers=manager_headers,
    )
    assert blocked.status_code == 422

    await client.patch(
        "/api/v1/admin/field-configs/property/lat",
        json={"visible": True},
        headers=super_admin_headers,
    )
    ok = await client.post(
        "/api/v1/properties",
        json={"name": "T", "b2b_rate": "1", "b2c_rate": "1", "lat": 12.34},
        headers=manager_headers,
    )
    assert ok.status_code == 201
    assert ok.json()["lat"] == 12.34


async def test_disabled_field_blocks_patch_too(
    client, super_admin_headers, manager_headers
):
    created = await client.post(
        "/api/v1/properties",
        json={"name": "T", "b2b_rate": "1", "b2c_rate": "1"},
        headers=manager_headers,
    )
    pid = created.json()["id"]

    await client.patch(
        "/api/v1/admin/field-configs/property/bedrooms",
        json={"visible": False},
        headers=super_admin_headers,
    )
    resp = await client.patch(
        f"/api/v1/properties/{pid}",
        json={"bedrooms": 3},
        headers=manager_headers,
    )
    assert resp.status_code == 422
    assert "bedrooms" in resp.json()["detail"]["fields"]


async def test_unknown_entity_returns_404(client, manager_headers):
    resp = await client.get(
        "/api/v1/admin/field-configs/zzz", headers=manager_headers
    )
    assert resp.status_code == 404


async def test_update_unknown_field_returns_404(client, super_admin_headers):
    resp = await client.patch(
        "/api/v1/admin/field-configs/property/not_a_real_field",
        json={"visible": False},
        headers=super_admin_headers,
    )
    assert resp.status_code == 404
