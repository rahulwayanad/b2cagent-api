"""Bidding API tests.

Focuses on the two rules the spec calls out explicitly:
  1. bid amount must be >= property.b2b_rate
  2. agents can never see other agents' bids or amounts
…plus accept/reject flow + auto-rejection + background notifications.
"""
from __future__ import annotations

from datetime import date, timedelta


def _future(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


async def _create_property(client, manager_headers, **overrides) -> str:
    payload = {
        "name": "Sunset Villa",
        "description": "Beachfront",
        "location_text": "Goa",
        "b2b_rate": "100.00",
        "b2c_rate": "150.00",
    }
    payload.update(overrides)
    resp = await client.post(
        "/api/v1/properties", json=payload, headers=manager_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---- property visibility (no b2b_rate for agents) -------------------------


async def test_agent_lists_only_active_properties_and_no_b2b_rate(
    client, manager_headers, agent_headers
):
    active_id = await _create_property(client, manager_headers, name="Active")
    closed_id = await _create_property(client, manager_headers, name="ToClose")
    await client.post(
        f"/api/v1/properties/{closed_id}/close", headers=manager_headers
    )

    resp = await client.get(
        "/api/v1/properties/available", headers=agent_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    ids = {p["id"] for p in body["items"]}
    assert active_id in ids
    assert closed_id not in ids
    for p in body["items"]:
        assert "b2b_rate" not in p
        assert "b2c_rate" in p


async def test_agent_detail_omits_b2b_rate(client, manager_headers, agent_headers):
    pid = await _create_property(client, manager_headers)
    resp = await client.get(
        f"/api/v1/properties/available/{pid}", headers=agent_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "b2b_rate" not in body
    assert body["b2c_rate"] == "150.00"


async def test_manager_cannot_use_agent_browsing_endpoints(client, manager_headers):
    resp = await client.get(
        "/api/v1/properties/available", headers=manager_headers
    )
    assert resp.status_code == 403


# ---- bid placement validation ---------------------------------------------


async def test_bid_below_b2b_rate_is_rejected(
    client, manager_headers, agent_headers
):
    pid = await _create_property(client, manager_headers, b2b_rate="100.00")
    resp = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(), "amount": "50.00"},
        headers=agent_headers,
    )
    assert resp.status_code == 400
    assert "at least 100" in resp.json()["detail"]


async def test_bid_at_b2b_rate_is_accepted(client, manager_headers, agent_headers):
    pid = await _create_property(client, manager_headers, b2b_rate="100.00")
    resp = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(), "amount": "100.00"},
        headers=agent_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["amount"] == "100.00"
    assert body["property_name"] == "Sunset Villa"


async def test_bid_above_b2b_rate_is_accepted(client, manager_headers, agent_headers):
    pid = await _create_property(client, manager_headers, b2b_rate="100.00")
    resp = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(), "amount": "200.00"},
        headers=agent_headers,
    )
    assert resp.status_code == 201


async def test_bid_on_non_active_property_rejected(
    client, manager_headers, agent_headers
):
    pid = await _create_property(client, manager_headers)
    await client.post(f"/api/v1/properties/{pid}/close", headers=manager_headers)
    resp = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(), "amount": "200.00"},
        headers=agent_headers,
    )
    assert resp.status_code == 400
    assert "not active" in resp.json()["detail"]


async def test_bid_past_date_rejected(client, manager_headers, agent_headers):
    pid = await _create_property(client, manager_headers)
    past = (date.today() - timedelta(days=1)).isoformat()
    resp = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": past, "amount": "150.00"},
        headers=agent_headers,
    )
    assert resp.status_code == 400
    assert "future" in resp.json()["detail"]


async def test_duplicate_bid_rejected(client, manager_headers, agent_headers):
    pid = await _create_property(client, manager_headers)
    body = {"property_id": pid, "bid_date": _future(), "amount": "150.00"}
    first = await client.post("/api/v1/bids", json=body, headers=agent_headers)
    assert first.status_code == 201
    second = await client.post("/api/v1/bids", json=body, headers=agent_headers)
    assert second.status_code == 400


# ---- agent bid visibility (their own only) --------------------------------


async def test_agent_sees_only_own_bids(
    client, manager_headers, agent_headers, other_agent_headers
):
    pid = await _create_property(client, manager_headers)
    await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(1), "amount": "150.00"},
        headers=agent_headers,
    )
    await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(2), "amount": "200.00"},
        headers=other_agent_headers,
    )

    a = await client.get("/api/v1/bids/mine", headers=agent_headers)
    b = await client.get("/api/v1/bids/mine", headers=other_agent_headers)
    assert len(a.json()) == 1
    assert len(b.json()) == 1
    assert a.json()[0]["amount"] == "150.00"
    assert b.json()[0]["amount"] == "200.00"


# ---- withdraw -------------------------------------------------------------


async def test_agent_can_withdraw_own_pending_bid(
    client, manager_headers, agent_headers
):
    pid = await _create_property(client, manager_headers)
    placed = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(), "amount": "150.00"},
        headers=agent_headers,
    )
    bid_id = placed.json()["id"]
    resp = await client.delete(
        f"/api/v1/bids/{bid_id}", headers=agent_headers
    )
    assert resp.status_code == 204

    mine = await client.get("/api/v1/bids/mine", headers=agent_headers)
    assert mine.json()[0]["status"] == "withdrawn"


async def test_agent_cannot_withdraw_another_agents_bid(
    client, manager_headers, agent_headers, other_agent_headers
):
    pid = await _create_property(client, manager_headers)
    placed = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(), "amount": "150.00"},
        headers=agent_headers,
    )
    bid_id = placed.json()["id"]
    resp = await client.delete(
        f"/api/v1/bids/{bid_id}", headers=other_agent_headers
    )
    assert resp.status_code == 404  # don't leak existence


# ---- manager view + decisions --------------------------------------------


async def test_manager_sees_all_bids_with_agents_sorted_by_amount(
    client, manager_headers, agent_headers, other_agent_headers
):
    pid = await _create_property(client, manager_headers)
    await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(1), "amount": "150.00"},
        headers=agent_headers,
    )
    await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(2), "amount": "200.00"},
        headers=other_agent_headers,
    )

    resp = await client.get(
        f"/api/v1/properties/{pid}/bids", headers=manager_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    # sorted by amount DESC
    assert body[0]["amount"] == "200.00"
    assert body[1]["amount"] == "150.00"
    # agent identities exposed to manager
    assert {b["agent_name"] for b in body} == {"Test Agent", "Other Agent"}


async def test_manager_cannot_view_other_managers_property_bids(
    client, manager_headers, other_manager_headers, agent_headers
):
    pid = await _create_property(client, manager_headers)
    await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(), "amount": "150.00"},
        headers=agent_headers,
    )
    resp = await client.get(
        f"/api/v1/properties/{pid}/bids", headers=other_manager_headers
    )
    assert resp.status_code == 403


async def test_agent_cannot_call_manager_bid_endpoints(
    client, manager_headers, agent_headers
):
    pid = await _create_property(client, manager_headers)
    placed = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(), "amount": "150.00"},
        headers=agent_headers,
    )
    bid_id = placed.json()["id"]

    accept = await client.patch(
        f"/api/v1/bids/{bid_id}/accept", headers=agent_headers
    )
    reject = await client.patch(
        f"/api/v1/bids/{bid_id}/reject", headers=agent_headers
    )
    listing = await client.get(
        f"/api/v1/properties/{pid}/bids", headers=agent_headers
    )
    assert accept.status_code == 403
    assert reject.status_code == 403
    assert listing.status_code == 403


async def test_accept_auto_rejects_other_pending_bids_for_same_date(
    client, manager_headers, agent_headers, other_agent_headers,
    email_sender,
):
    pid = await _create_property(client, manager_headers)
    bid_date = _future(5)
    winner = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": bid_date, "amount": "200.00"},
        headers=agent_headers,
    )
    loser = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": bid_date, "amount": "150.00"},
        headers=other_agent_headers,
    )
    # An unrelated bid on a different date should NOT be auto-rejected.
    other_date = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(20), "amount": "300.00"},
        headers=other_agent_headers,
    )

    resp = await client.patch(
        f"/api/v1/bids/{winner.json()['id']}/accept",
        headers=manager_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    listing = (
        await client.get(
            f"/api/v1/properties/{pid}/bids", headers=manager_headers
        )
    ).json()
    by_id = {b["id"]: b for b in listing}
    assert by_id[winner.json()["id"]]["status"] == "accepted"
    assert by_id[loser.json()["id"]]["status"] == "rejected"
    assert by_id[other_date.json()["id"]]["status"] == "pending"

    # Notifications: 1 accept + 1 auto-reject. The "different date" bid stays
    # untouched and is NOT notified.
    statuses = sorted(
        e["subject"].split(" was ")[1] for e in email_sender.sent
    )
    assert statuses == ["accepted", "rejected"]


async def test_reject_changes_status_and_sends_notification(
    client, manager_headers, agent_headers, email_sender, sms_sender
):
    pid = await _create_property(client, manager_headers)
    placed = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(), "amount": "150.00"},
        headers=agent_headers,
    )
    bid_id = placed.json()["id"]
    resp = await client.patch(
        f"/api/v1/bids/{bid_id}/reject", headers=manager_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert any("rejected" in e["subject"] for e in email_sender.sent)
    # No phone on default agent fixture → no SMS
    assert sms_sender.sent == []


async def test_cannot_accept_or_reject_non_pending_bid(
    client, manager_headers, agent_headers
):
    pid = await _create_property(client, manager_headers)
    placed = await client.post(
        "/api/v1/bids",
        json={"property_id": pid, "bid_date": _future(), "amount": "150.00"},
        headers=agent_headers,
    )
    bid_id = placed.json()["id"]
    await client.patch(f"/api/v1/bids/{bid_id}/reject", headers=manager_headers)
    again = await client.patch(
        f"/api/v1/bids/{bid_id}/accept", headers=manager_headers
    )
    assert again.status_code == 400


async def test_existing_property_detail_route_still_works(
    client, manager_headers
):
    """Sanity check that adding /properties/available didn't shadow
    GET /properties/{property_id} for the manager."""
    pid = await _create_property(client, manager_headers)
    resp = await client.get(
        f"/api/v1/properties/{pid}", headers=manager_headers
    )
    assert resp.status_code == 200
    assert "b2b_rate" in resp.json()
