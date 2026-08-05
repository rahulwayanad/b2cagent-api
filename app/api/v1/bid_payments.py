"""Bid payment flow.

Booking creation no longer happens at bid-accept time. Instead:
  1. Manager accepts bid → bid.status = accepted (no booking yet).
  2. Agent collects cash from the customer and POSTs to /bids/{id}/payment
     to record a payment in status=initiated.
  3. Manager confirms receipt via PATCH /bid-payments/{id}/confirm →
     payment.status=confirmed AND the Booking row is created here.

Online payments (future): a gateway webhook will create the payment record
directly in status=confirmed and trigger the same booking-creation path.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user, require_active_role
from app.models import (
    Bid,
    BidPayment,
    BidStatus,
    Booking,
    BookingStatus,
    Lead,
    PaymentMethod,
    PaymentStatus,
    User,
    UserRole,
)
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.models import Property
from app.schemas.bid_payment import (
    BidPaymentCreateIn,
    BidPaymentOut,
    CheckoutDataOut,
    CheckoutLead,
    CheckoutManager,
    CheckoutPricing,
    CheckoutProperty,
)
from app.services import notification_service as notif_service
from app.services.email_template_service import send_templated_email
from app.services.notifications import get_email_sender

router = APIRouter(tags=["bid-payments"])

agent_dep = require_active_role(UserRole.agent)
manager_dep = require_active_role(UserRole.manager)


@router.post(
    "/bids/{bid_id}/payment",
    status_code=status.HTTP_201_CREATED,
    response_model=BidPaymentOut,
)
async def create_bid_payment(
    bid_id: uuid.UUID,
    payload: BidPaymentCreateIn,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> BidPaymentOut:
    bid = await db.scalar(
        select(Bid)
        .options(selectinload(Bid.payment))
        .where(Bid.id == bid_id)
    )
    if bid is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="bid not found"
        )
    if bid.agent_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not own this bid",
        )
    if bid.status != BidStatus.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payment can only be recorded on accepted bids",
        )
    if bid.payment is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="payment already recorded for this bid",
        )
    if payload.method == "online":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="online payment is not enabled yet",
        )

    # Issue an invoice number once on creation. Format: B2C-YYYYMMDD-<6 hex>
    invoice_no = _next_invoice_no(bid.id)
    address_snapshot = (
        payload.invoice_address.model_dump() if payload.invoice_address else None
    )
    channels_csv = (
        ",".join(payload.delivery_channels) if payload.delivery_channels else "email"
    )

    payment = BidPayment(
        bid_id=bid.id,
        method=PaymentMethod.cash,
        status=PaymentStatus.initiated,
        amount=bid.amount,
        notes=payload.notes,
        invoice_no=invoice_no,
        invoice_address_json=address_snapshot,
        delivery_channels=channels_csv,
    )
    db.add(payment)
    await notif_service.on_payment_initiated(db, bid)

    # Fire the customer-facing invoice email if we have a destination address
    # and email is in the chosen channels. Best-effort — swallow errors so a
    # transient SMTP blip doesn't roll back the payment record.
    if (
        "email" in (payload.delivery_channels or ["email"])
        and payload.invoice_address
        and payload.invoice_address.email
    ):
        try:
            await _send_customer_invoice_email(
                db, bid=bid, payment=payment, addr=payload.invoice_address
            )
        except Exception:  # noqa: BLE001
            pass

    await db.commit()
    await db.refresh(payment)
    return BidPaymentOut.model_validate(payment)


def _next_invoice_no(bid_id: uuid.UUID) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    short = uuid.uuid4().hex[:6].upper()
    return f"B2C-{today}-{short}"


async def _send_customer_invoice_email(
    db: AsyncSession,
    *,
    bid: Bid,
    payment: BidPayment,
    addr,
) -> None:
    """Send the invoice email to the customer. The invoice is *billed by*
    the property owner (manager) — the body shows their name/business as
    the issuer, not the agent."""
    prop = await db.scalar(
        select(Property).options(selectinload(Property.manager)).where(
            Property.id == bid.property_id
        )
    )
    if prop is None or prop.manager is None:
        return
    nights = max(
        1, (bid.check_out - bid.check_in).days if bid.check_out and bid.check_in else 1
    )
    per_night = float(prop.b2c_rate or bid.amount)
    total = per_night * nights
    invoice_url = (
        f"{settings.FRONTEND_BASE_URL.rstrip('/')}/agent/bookings/{bid.id}/payment"
    )
    await send_templated_email(
        db,
        get_email_sender(),
        code="invoice_issued",
        to=addr.email,
        context={
            "customer_name": addr.name,
            "invoice_no": payment.invoice_no or "",
            "property_name": prop.name,
            "manager_name": prop.manager.full_name,
            "manager_email": prop.manager.email,
            "manager_phone": prop.manager.phone or "",
            "manager_business_location": prop.manager.default_location or "",
            "check_in": bid.check_in.isoformat() if bid.check_in else "",
            "check_out": bid.check_out.isoformat() if bid.check_out else "",
            "nights": str(nights),
            "rate_per_night": f"{per_night:,.0f}",
            "amount_total": f"{total:,.0f}",
            "link_url": invoice_url,
        },
        fallback_subject="Invoice for your booking at {property_name}",
        fallback_body=(
            "Hi {customer_name},\n\n"
            "Invoice {invoice_no} for {nights} night(s) at {property_name}.\n"
            "Total: ₹{amount_total}\n"
            "Cash on Delivery — pay at check-in.\n\n"
            "Issued on behalf of: {manager_name}\n"
        ),
    )


@router.patch(
    "/bid-payments/{payment_id}/confirm", response_model=BidPaymentOut
)
async def confirm_bid_payment(
    payment_id: uuid.UUID,
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
) -> BidPaymentOut:
    payment = await db.scalar(
        select(BidPayment)
        .options(
            selectinload(BidPayment.bid).selectinload(Bid.property),
            selectinload(BidPayment.bid).selectinload(Bid.agent),
            selectinload(BidPayment.bid).selectinload(Bid.lead),
        )
        .where(BidPayment.id == payment_id)
    )
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="payment not found"
        )
    bid = payment.bid
    if bid.property.manager_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not own the property for this payment",
        )
    if payment.status == PaymentStatus.confirmed:
        # Idempotent — confirming twice should not double-book.
        return BidPaymentOut.model_validate(payment)

    payment.status = PaymentStatus.confirmed
    payment.confirmed_at = datetime.now(timezone.utc)

    # Booking is created on payment confirmation. No-op if one somehow exists
    # already (shouldn't, but guards against duplicates if the flow is rerun).
    existing_booking = await db.scalar(
        select(Booking).where(Booking.bid_id == bid.id)
    )
    if existing_booking is None:
        lead: Lead | None = bid.lead
        booking = Booking(
            property_id=bid.property_id,
            lead_id=bid.lead_id,
            bid_id=bid.id,
            agent_id=bid.agent_id,
            customer_name=lead.customer_name if lead else bid.agent.full_name,
            customer_email=lead.customer_email if lead else bid.agent.email,
            customer_phone=lead.customer_phone if lead else bid.agent.phone,
            check_in=bid.check_in,
            check_out=bid.check_out,
            guests=(lead.adults + (lead.children or 0)) if lead else 1,
            amount=bid.amount,
            status=BookingStatus.active,
        )
        db.add(booking)

    # Once the booking lands, every other live bid on this lead — same
    # property or different — loses. The customer is now booked; no other
    # manager should be able to accept a stale bid for them.
    others = (
        await db.scalars(
            select(Bid).where(
                Bid.lead_id == bid.lead_id,
                Bid.id != bid.id,
                Bid.status.in_(
                    [
                        BidStatus.pending,
                        BidStatus.on_hold,
                        BidStatus.accepted,
                    ]
                ),
            )
        )
    ).all()
    for o in others:
        o.status = BidStatus.rejected
        await notif_service.on_bid_rejected(db, o)

    await notif_service.on_payment_confirmed(db, bid)
    await db.commit()
    await db.refresh(payment)
    return BidPaymentOut.model_validate(payment)


@router.get("/bids/{bid_id}/checkout", response_model=CheckoutDataOut)
async def get_checkout_data(
    bid_id: uuid.UUID,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> CheckoutDataOut:
    """Everything the agent's payment page needs in one round trip.

    Includes the *manager* (so the invoice can show 'billed by' that owner),
    the lead (for prefilling the customer invoice address), and a derived
    pricing breakdown. Returns 404 if the bid isn't owned by this agent.
    """
    bid = await db.scalar(
        select(Bid)
        .options(
            selectinload(Bid.property).selectinload(Property.manager),
            selectinload(Bid.property).selectinload(Property.photos),
            selectinload(Bid.lead),
            selectinload(Bid.payment),
        )
        .where(Bid.id == bid_id)
    )
    if bid is None or bid.agent_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="bid not found"
        )

    prop = bid.property
    manager = prop.manager if prop else None
    if prop is None or manager is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="property or owner missing for this bid",
        )

    nights = max(
        1,
        (bid.check_out - bid.check_in).days
        if (bid.check_in and bid.check_out)
        else 1,
    )
    b2c_total = (prop.b2c_rate or bid.amount) * nights
    bid_total = bid.amount * nights
    # Commission = (B2C list − agent bid) per night × nights. Floor at 0.
    from decimal import Decimal as _D

    commission_amount = max(_D("0"), (prop.b2c_rate or bid.amount) - bid.amount) * nights
    commission_rate = (
        (commission_amount / b2c_total) if b2c_total > 0 else _D("0")
    )

    primary_photo = next(
        (ph for ph in (prop.photos or []) if getattr(ph, "is_primary", False)),
        None,
    )
    if primary_photo is None and prop.photos:
        primary_photo = prop.photos[0]

    lead_dto: CheckoutLead | None = None
    if bid.lead is not None:
        lead_dto = CheckoutLead(
            id=bid.lead.id,
            customer_name=bid.lead.customer_name,
            customer_email=bid.lead.customer_email,
            customer_phone=bid.lead.customer_phone,
            customer_location_text=bid.lead.customer_location_text,
            adults=bid.lead.adults,
            children=bid.lead.children,
        )

    return CheckoutDataOut(
        bid_id=bid.id,
        bid_status=bid.status.value,
        check_in=datetime.combine(bid.check_in, datetime.min.time(), tzinfo=timezone.utc),
        check_out=datetime.combine(bid.check_out, datetime.min.time(), tzinfo=timezone.utc),
        property=CheckoutProperty(
            id=prop.id,
            name=prop.name,
            photo_url=primary_photo.url if primary_photo else None,
            location_text=prop.location_text,
            bedrooms=prop.bedrooms,
            guests=prop.guests,
        ),
        manager=CheckoutManager(
            id=manager.id,
            full_name=manager.full_name,
            email=manager.email,
            phone=manager.phone,
            business_location=manager.default_location,
        ),
        lead=lead_dto,
        pricing=CheckoutPricing(
            nights=nights,
            b2c_rate=prop.b2c_rate or bid.amount,
            b2b_rate=prop.b2b_rate or bid.amount,
            bid_amount=bid.amount,
            bid_total=bid_total,
            b2c_total=b2c_total,
            commission_amount=commission_amount,
            commission_rate=commission_rate,
        ),
        payment=(
            BidPaymentOut.model_validate(bid.payment) if bid.payment else None
        ),
    )


# Light-weight introspection so the agent UI can poll for status if needed.
@router.get("/bids/{bid_id}/payment", response_model=BidPaymentOut | None)
async def get_bid_payment(
    bid_id: uuid.UUID,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> BidPaymentOut | None:
    bid = await db.scalar(
        select(Bid).options(selectinload(Bid.payment)).where(Bid.id == bid_id)
    )
    if bid is None or bid.agent_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="bid not found"
        )
    if bid.payment is None:
        return None
    return BidPaymentOut.model_validate(bid.payment)


# ---- Printable HTML invoice ----------------------------------------------
#
# Returns a self-contained HTML document the browser can render full-screen
# (and Save-as-PDF via the print dialog). Authorisation: agent who placed
# the bid OR manager who owns the property.


@router.get(
    "/bid-payments/{payment_id}/invoice", response_class=HTMLResponse
)
async def get_invoice_html(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    payment = await db.scalar(
        select(BidPayment)
        .options(
            selectinload(BidPayment.bid)
            .selectinload(Bid.property)
            .selectinload(Property.manager)
        )
        .where(BidPayment.id == payment_id)
    )
    if payment is None or payment.bid is None or payment.bid.property is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invoice not found"
        )
    bid = payment.bid
    prop = bid.property
    manager = prop.manager
    if user.id not in (bid.agent_id, manager.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you cannot view this invoice",
        )

    html = _render_invoice_html(payment=payment, bid=bid, prop=prop, manager=manager)
    return HTMLResponse(content=html)


def _render_invoice_html(
    *, payment: BidPayment, bid: Bid, prop: Property, manager: User
) -> str:
    import html as _h

    addr = payment.invoice_address_json or {}
    customer_name = _h.escape(addr.get("name") or "Customer")
    customer_phone = _h.escape(addr.get("phone") or "")
    customer_email = _h.escape(addr.get("email") or "")
    customer_gstin = _h.escape(addr.get("gstin") or "")
    address_lines = [
        addr.get("line1"),
        ", ".join(p for p in [addr.get("city"), addr.get("state"), addr.get("pin_code")] if p),
    ]
    customer_address = "<br>".join(_h.escape(x) for x in address_lines if x)

    nights = max(
        1,
        (bid.check_out - bid.check_in).days
        if (bid.check_in and bid.check_out)
        else 1,
    )
    per_night = prop.b2c_rate or bid.amount
    total = float(per_night) * nights
    issued_on = payment.created_at.strftime("%d %b %Y")
    invoice_no = _h.escape(payment.invoice_no or str(payment.id)[:8].upper())

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<title>Invoice {invoice_no}</title>
<style>
  @page {{ size: A4; margin: 18mm; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #15201B; background: #F6F4EF;
    margin: 0; padding: 24px;
  }}
  .sheet {{
    max-width: 760px; margin: 0 auto; background: #fff;
    padding: 36px; border-radius: 14px;
    box-shadow: 0 4px 20px rgba(0,0,0,.06);
  }}
  .head {{ display: flex; justify-content: space-between; align-items: start; gap: 24px; border-bottom: 1px solid #EFEAE0; padding-bottom: 18px; margin-bottom: 24px; }}
  .brand {{ font-size: 28px; font-weight: 700; color: #1F3A2E; letter-spacing: -0.5px; }}
  .brand .accent {{ color: #E36414; }}
  .brand-sub {{ font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: #8A847B; margin-top: 4px; }}
  .meta {{ text-align: right; font-size: 12px; color: #5B5750; }}
  .meta .label {{ color: #8A847B; text-transform: uppercase; font-size: 10.5px; letter-spacing: 0.1em; }}
  .meta .no {{ font-size: 16px; font-weight: 600; color: #15201B; margin-top: 2px; }}
  .parties {{ display: grid; grid-template-columns: 1fr 1fr; gap: 32px; margin-bottom: 28px; }}
  .party h3 {{ margin: 0 0 6px; font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; color: #8A847B; font-weight: 600; }}
  .party .name {{ font-size: 14.5px; font-weight: 600; color: #15201B; }}
  .party .lines {{ margin-top: 4px; font-size: 12.5px; color: #5B5750; line-height: 1.6; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin: 8px 0 20px; }}
  th {{ background: #FAF8F3; text-align: left; padding: 10px 12px; color: #5B5750; font-weight: 600; border-bottom: 1px solid #EFEAE0; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; }}
  td {{ padding: 12px; border-bottom: 1px solid #EFEAE0; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tfoot td {{ border-bottom: none; font-weight: 600; }}
  .total-row td {{ background: #1F3A2E; color: #F6F4EF; padding: 14px 12px; font-size: 16px; }}
  .pill {{ display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em; background: #D4E8DD; color: #1F5A3E; }}
  .footer {{ margin-top: 28px; padding-top: 16px; border-top: 1px dashed #EFEAE0; font-size: 11.5px; color: #8A847B; line-height: 1.6; }}
  .actions {{ text-align: center; margin: 16px 0 24px; }}
  .actions button {{ background: #1F3A2E; color: #F6F4EF; border: none; padding: 10px 22px; border-radius: 999px; font-size: 13px; font-weight: 500; cursor: pointer; }}
  @media print {{ body {{ background: #fff; padding: 0; }} .sheet {{ box-shadow: none; }} .actions {{ display: none; }} }}
</style>
</head>
<body>
  <div class="actions">
    <button onclick="window.print()">Print / Save as PDF</button>
  </div>
  <div class="sheet">
    <div class="head">
      <div>
        <div class="brand">B2C Tour <span class="accent">Agent.</span></div>
        <div class="brand-sub">Invoice · Cash on Delivery</div>
      </div>
      <div class="meta">
        <div class="label">Invoice no.</div>
        <div class="no">{invoice_no}</div>
        <div style="margin-top:8px">{_h.escape(issued_on)}</div>
      </div>
    </div>

    <div class="parties">
      <div class="party">
        <h3>Billed by</h3>
        <div class="name">{_h.escape(manager.full_name)}</div>
        <div class="lines">
          {_h.escape(manager.default_location or prop.location_text or "")}<br>
          {_h.escape(manager.email)}{(' · ' + _h.escape(manager.phone)) if manager.phone else ''}
        </div>
      </div>
      <div class="party">
        <h3>Billed to</h3>
        <div class="name">{customer_name}</div>
        <div class="lines">
          {customer_address or '—'}<br>
          {('☎ ' + customer_phone) if customer_phone else ''}{(' · ✉ ' + customer_email) if customer_email else ''}
          {('<br>GSTIN: ' + customer_gstin) if customer_gstin else ''}
        </div>
      </div>
    </div>

    <table>
      <thead>
        <tr>
          <th>Description</th>
          <th class="num">Nights</th>
          <th class="num">Rate / night</th>
          <th class="num">Amount</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            Stay at <strong>{_h.escape(prop.name)}</strong><br>
            <span style="color:#8A847B;font-size:11.5px">
              {bid.check_in.strftime('%d %b %Y') if bid.check_in else ''} → {bid.check_out.strftime('%d %b %Y') if bid.check_out else ''}
            </span>
          </td>
          <td class="num">{nights}</td>
          <td class="num">₹{float(per_night):,.0f}</td>
          <td class="num">₹{total:,.0f}</td>
        </tr>
      </tbody>
      <tfoot>
        <tr class="total-row">
          <td colspan="3" style="text-align:right">Total (all-in)</td>
          <td class="num">₹{total:,.0f}</td>
        </tr>
      </tfoot>
    </table>

    <p><span class="pill">● Cash on Delivery</span> &nbsp; Cash to be collected by the property at check-in.</p>

    <div class="footer">
      <strong style="color:#15201B">Notes:</strong> {_h.escape(payment.notes or '—')}<br>
      Generated by B2C Tour Agent · b2cagent.xyz · This is a system-generated invoice and is valid without signature.
    </div>
  </div>
</body></html>"""


