import asyncio
import math
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import (
    EmailTemplate,
    FieldConfig,
    Property,
    PropertyStatus,
    SubscriptionPlan,
    User,
    UserRole,
    UserSubscription,
)
from app.schemas.catalog import FieldConfigOut, FieldConfigUpdate
from app.schemas.email_template import (
    EmailTemplateOut,
    EmailTemplateUpdateIn,
)
from app.services.lead_expiry_service import expire_overdue_leads
from app.schemas.subscription import (
    AssignPlanIn,
    PlanUpdateIn,
    SubscriptionPlanOut,
    UserSubscriptionOut,
)
from app.services.catalog import FIELD_CONFIG_ENTITIES
from app.services.field_config_service import ensure_defaults

router = APIRouter(prefix="/admin", tags=["admin"])

super_admin_dep = require_role(UserRole.super_admin)


@router.get(
    "/field-configs/{entity}", response_model=list[FieldConfigOut]
)
async def list_field_configs(
    entity: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[FieldConfig]:
    if entity not in FIELD_CONFIG_ENTITIES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown entity {entity!r}",
        )
    await ensure_defaults(db, entity)
    rows = (
        await db.scalars(
            select(FieldConfig)
            .where(FieldConfig.entity == entity)
            .order_by(FieldConfig.field_name.asc())
        )
    ).all()
    return list(rows)


@router.patch(
    "/field-configs/{entity}/{field_name}", response_model=FieldConfigOut
)
async def update_field_config(
    entity: str,
    field_name: str,
    payload: FieldConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> FieldConfig:
    if entity not in FIELD_CONFIG_ENTITIES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown entity {entity!r}",
        )
    if field_name not in FIELD_CONFIG_ENTITIES[entity]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown field {field_name!r} for entity {entity!r}",
        )
    await ensure_defaults(db, entity)
    config = await db.scalar(
        select(FieldConfig).where(
            FieldConfig.entity == entity,
            FieldConfig.field_name == field_name,
        )
    )
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="field config not found"
        )
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no fields supplied",
        )
    for key, value in updates.items():
        setattr(config, key, value)
    await db.commit()
    await db.refresh(config)
    return config


# ---- Subscription plan catalog --------------------------------------------


@router.get("/subscription-plans", response_model=list[SubscriptionPlanOut])
async def list_subscription_plans(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> list[SubscriptionPlan]:
    rows = (
        await db.scalars(
            select(SubscriptionPlan).order_by(SubscriptionPlan.price.asc())
        )
    ).all()
    return list(rows)


@router.patch(
    "/subscription-plans/{plan_id}", response_model=SubscriptionPlanOut
)
async def update_subscription_plan(
    plan_id: uuid.UUID,
    payload: PlanUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> SubscriptionPlan:
    plan = await db.get(SubscriptionPlan, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="subscription plan not found",
        )
    # exclude_unset so admins can clear a limit by sending null explicitly,
    # without forcing them to send every field on a partial edit.
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(plan, field, value)
    await db.commit()
    await db.refresh(plan)
    return plan


# ---- User administration --------------------------------------------------


class UserAdminOut(BaseModel):
    """Admin-facing user row with the attached plan, if any."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    phone: str | None
    is_active: bool
    plan_code: str | None
    monthly_bid_limit: int | None
    created_at: datetime


async def _to_admin_row(u: User, db: AsyncSession) -> UserAdminOut:
    sub = await db.scalar(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.user_id == u.id)
    )
    plan = sub.plan if sub else None
    return UserAdminOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        phone=u.phone,
        is_active=u.is_active,
        plan_code=plan.code if plan else None,
        monthly_bid_limit=plan.monthly_bid_limit if plan else None,
        created_at=u.created_at,
    )


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> list[UserAdminOut]:
    users = (
        await db.scalars(select(User).order_by(User.created_at.desc()))
    ).all()
    return [await _to_admin_row(u, db) for u in users]


async def _load_target_user(
    user_id: uuid.UUID, admin: User, db: AsyncSession
) -> User:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )
    if target.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you cannot modify your own account here",
        )
    return target


@router.patch("/users/{user_id}/disable", response_model=UserAdminOut)
async def disable_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(super_admin_dep),
) -> UserAdminOut:
    target = await _load_target_user(user_id, admin, db)
    target.is_active = False
    await db.commit()
    return await _to_admin_row(target, db)


@router.patch("/users/{user_id}/enable", response_model=UserAdminOut)
async def enable_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(super_admin_dep),
) -> UserAdminOut:
    target = await _load_target_user(user_id, admin, db)
    target.is_active = True
    await db.commit()
    return await _to_admin_row(target, db)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(super_admin_dep),
) -> None:
    target = await _load_target_user(user_id, admin, db)
    await db.delete(target)
    await db.commit()


@router.post(
    "/users/{user_id}/subscription", response_model=UserSubscriptionOut
)
async def assign_user_plan(
    user_id: uuid.UUID,
    payload: AssignPlanIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(super_admin_dep),
) -> UserSubscription:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )
    plan = await db.scalar(
        select(SubscriptionPlan).where(
            SubscriptionPlan.code == payload.plan_code
        )
    )
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"plan {payload.plan_code!r} not found",
        )

    existing = await db.scalar(
        select(UserSubscription).where(UserSubscription.user_id == target.id)
    )
    now = datetime.now(timezone.utc)
    if existing is None:
        sub = UserSubscription(
            user_id=target.id,
            plan_id=plan.id,
            starts_at=now,
        )
        db.add(sub)
    else:
        existing.plan_id = plan.id
        existing.starts_at = now
        existing.expires_at = None
        sub = existing
    await db.commit()
    # Re-load with the plan relationship populated for the response.
    out = await db.scalar(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.id == sub.id)
    )
    try:
        from app.services.email_template_service import send_templated_email
        from app.services.notifications import get_email_sender

        await send_templated_email(
            db,
            get_email_sender(),
            code="subscription_upgraded",
            to=target.email,
            context={
                "name": target.full_name,
                "plan_name": plan.name,
                "bid_limit": plan.monthly_bid_limit
                if plan.monthly_bid_limit is not None
                else "unlimited",
                "property_limit": plan.monthly_property_limit
                if plan.monthly_property_limit is not None
                else "unlimited",
                "link_url": (
                    f"{settings.FRONTEND_BASE_URL.rstrip('/')}/manager/profile"
                ),
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return out  # type: ignore[return-value]


# ---- Email templates ------------------------------------------------------


@router.get("/email-templates", response_model=list[EmailTemplateOut])
async def list_email_templates(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> list[EmailTemplate]:
    rows = (
        await db.scalars(
            select(EmailTemplate).order_by(EmailTemplate.code.asc())
        )
    ).all()
    return list(rows)


@router.patch(
    "/email-templates/{template_id}", response_model=EmailTemplateOut
)
async def update_email_template(
    template_id: uuid.UUID,
    payload: EmailTemplateUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> EmailTemplate:
    tmpl = await db.get(EmailTemplate, template_id)
    if tmpl is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        )
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(tmpl, field, value)
    await db.commit()
    await db.refresh(tmpl)
    return tmpl


# ---- Maintenance jobs -----------------------------------------------------


@router.post("/jobs/expire-leads")
async def run_expire_leads_job(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> dict[str, int]:
    """Manual trigger for the lead-expiry sweep. The same sweep also runs
    hourly via the in-process scheduler."""
    return await expire_overdue_leads(db)


# ---- Property import + admin-wide property list --------------------------
#
# Admin can on-board a property + its manager in one shot. The property lands
# in `draft` (unpublished) state so the manager can finish details and publish
# themselves. If the manager doesn't exist yet, we create them with role=manager
# (or upgrade an agent to `both`); they pick up the account later via OTP login.


class ImportRow(BaseModel):
    manager_email: str
    manager_name: str
    manager_phone: str | None = None
    property_name: str
    b2b_rate: Decimal
    b2c_rate: Decimal
    location_text: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    lat: float | None = None
    lng: float | None = None
    description: str | None = None


class ImportRequest(BaseModel):
    rows: list[ImportRow]


class ImportRowError(BaseModel):
    row_index: int
    message: str


class ImportSummary(BaseModel):
    rows_total: int
    users_created: int
    users_existing: int
    properties_created: int
    errors: list[ImportRowError]


def _normalize_email(s: str) -> str:
    return s.strip().lower()


async def _resolve_manager(
    db: AsyncSession, row: ImportRow
) -> tuple[User, bool]:
    """Return (user, created). Upgrades existing agent users to `both`."""
    email = _normalize_email(row.manager_email)
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        # If they're already an agent, also grant manager via 'both'.
        if existing.role == UserRole.agent:
            existing.role = UserRole.both
        return existing, False

    user = User(
        email=email,
        full_name=row.manager_name.strip(),
        phone=row.manager_phone.strip() if row.manager_phone else None,
        role=UserRole.manager,
        is_active=True,
        email_verified=False,
    )
    db.add(user)
    await db.flush()  # populate user.id without committing yet
    return user, True


@router.post("/import/properties", response_model=ImportSummary)
async def import_properties(
    payload: ImportRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> ImportSummary:
    """Bulk-create properties (and their owner-managers if missing) as drafts.

    Each row is processed in its own savepoint so a bad row doesn't poison the
    whole batch. The summary tallies successes and surfaces per-row errors.
    """
    if not payload.rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="rows is empty"
        )

    users_created = 0
    users_existing = 0
    properties_created = 0
    errors: list[ImportRowError] = []

    for idx, row in enumerate(payload.rows):
        try:
            if not row.manager_email or "@" not in row.manager_email:
                raise ValueError("manager_email must be a valid email")
            if not row.property_name.strip():
                raise ValueError("property_name is required")
            if row.b2b_rate < 0 or row.b2c_rate < 0:
                raise ValueError("rates must be non-negative")

            async with db.begin_nested():
                user, created = await _resolve_manager(db, row)
                prop = Property(
                    manager_id=user.id,
                    name=row.property_name.strip(),
                    description=row.description,
                    location_text=row.location_text,
                    street=row.street,
                    city=row.city,
                    # Domestic-only product: default state/country if missing.
                    state=(row.state or "Kerala"),
                    country=(row.country or "India"),
                    lat=row.lat,
                    lng=row.lng,
                    b2b_rate=row.b2b_rate,
                    b2c_rate=row.b2c_rate,
                    # Imported listings land unpublished so the manager can
                    # complete details and publish themselves.
                    status=PropertyStatus.draft,
                )
                db.add(prop)
            if created:
                users_created += 1
            else:
                users_existing += 1
            properties_created += 1
        except Exception as e:  # noqa: BLE001
            errors.append(
                ImportRowError(row_index=idx, message=str(e) or e.__class__.__name__)
            )

    await db.commit()
    return ImportSummary(
        rows_total=len(payload.rows),
        users_created=users_created,
        users_existing=users_existing,
        properties_created=properties_created,
        errors=errors,
    )


class AdminPropertyRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: PropertyStatus
    city: str | None
    state: str | None
    country: str | None
    b2b_rate: Decimal
    b2c_rate: Decimal
    created_at: datetime
    manager_id: uuid.UUID
    manager_name: str
    manager_email: str


class AdminPropertyListOut(BaseModel):
    items: list[AdminPropertyRow]
    total: int
    limit: int
    offset: int


@router.get("/properties", response_model=AdminPropertyListOut)
async def list_all_properties(
    search: str | None = None,
    status_filter: PropertyStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> AdminPropertyListOut:
    """All properties across every manager. Filter by name/city or status."""
    from sqlalchemy import func, or_

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    base = select(Property).options(selectinload(Property.manager))
    count_q = select(func.count()).select_from(Property)

    if search:
        like = f"%{search.strip()}%"
        cond = or_(
            Property.name.ilike(like),
            Property.city.ilike(like),
            Property.state.ilike(like),
            Property.country.ilike(like),
            Property.location_text.ilike(like),
        )
        base = base.where(cond)
        count_q = count_q.where(cond)
    if status_filter is not None:
        base = base.where(Property.status == status_filter)
        count_q = count_q.where(Property.status == status_filter)

    base = base.order_by(Property.created_at.desc()).limit(limit).offset(offset)

    total = (await db.scalar(count_q)) or 0
    rows = (await db.scalars(base)).all()

    items = [
        AdminPropertyRow(
            id=p.id,
            name=p.name,
            status=p.status,
            city=p.city,
            state=p.state,
            country=p.country,
            b2b_rate=p.b2b_rate,
            b2c_rate=p.b2c_rate,
            created_at=p.created_at,
            manager_id=p.manager.id,
            manager_name=p.manager.full_name,
            manager_email=p.manager.email,
        )
        for p in rows
    ]
    return AdminPropertyListOut(
        items=items, total=int(total), limit=limit, offset=offset
    )


# ---- OSM Overpass resort sync --------------------------------------------
#
# Free alternative to Google Places. We query OpenStreetMap's Overpass API for
# tourism objects (resort, hotel, guest_house, hostel, chalet) inside a radius,
# then create draft properties + manager users. OSM exposes phone, website,
# address, lat/lng — but never email (privacy). We synthesise an email per
# manager as `<phone>@b2cagent.xyz` so accounts have a unique identifier; the
# manager signs in with that email + OTP later.

OSM_TOURISM_KINDS = ("resort", "hotel", "guest_house", "hostel", "chalet")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MANAGER_EMAIL_DOMAIN = "b2cagent.xyz"


def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _normalize_phone(raw: str | None) -> str | None:
    """Strip everything except digits; if it lacks a country code, prefix +91
    (the product is India-only). Returns None if there are fewer than 8 digits."""
    if not raw:
        return None
    digits = _digits_only(raw)
    if len(digits) < 8:
        return None
    # 10-digit local number → assume India.
    if len(digits) == 10:
        digits = "91" + digits
    return "+" + digits


def _phone_local_part(phone: str) -> str:
    """Email local-part from a normalised phone: keep digits only."""
    return _digits_only(phone)


class OsmResort(BaseModel):
    osm_id: int
    osm_type: str  # node | way | relation
    name: str
    phone: str | None  # normalised; None if missing/invalid
    raw_phone: str | None
    website: str | None
    lat: float
    lng: float
    street: str | None
    city: str | None
    state: str | None
    country: str | None
    location_text: str | None
    has_phone: bool
    # True if a user with this phone (or this property name + manager) already
    # exists — useful for the preview UI to show what'd be skipped vs created.
    manager_exists: bool


class OsmPreviewOut(BaseModel):
    items: list[OsmResort]
    total: int


def _tag(tags: dict, key: str) -> str | None:
    v = tags.get(key)
    return v.strip() if isinstance(v, str) and v.strip() else None


def _parse_osm_element(el: dict) -> OsmResort | None:
    tags = el.get("tags") or {}
    name = _tag(tags, "name")
    if not name:
        return None
    # Ways/relations return coords under "center"; nodes have direct lat/lon.
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lng = el.get("lon") or (el.get("center") or {}).get("lon")
    if lat is None or lng is None:
        return None
    raw_phone = (
        _tag(tags, "phone")
        or _tag(tags, "contact:phone")
        or _tag(tags, "contact:mobile")
    )
    phone = _normalize_phone(raw_phone)
    website = (
        _tag(tags, "website") or _tag(tags, "contact:website") or _tag(tags, "url")
    )
    street = _tag(tags, "addr:street")
    city = _tag(tags, "addr:city") or _tag(tags, "addr:town")
    state = _tag(tags, "addr:state")
    country = _tag(tags, "addr:country")
    parts = [p for p in (street, city, state, country) if p]
    location_text = ", ".join(parts) if parts else None
    return OsmResort(
        osm_id=el["id"],
        osm_type=el.get("type", "node"),
        name=name,
        phone=phone,
        raw_phone=raw_phone,
        website=website,
        lat=float(lat),
        lng=float(lng),
        street=street,
        city=city,
        state=state,
        country=country,
        location_text=location_text,
        has_phone=phone is not None,
        manager_exists=False,
    )


def _build_overpass_query(lat: float, lng: float, radius_m: int) -> str:
    kinds = "|".join(OSM_TOURISM_KINDS)
    return f"""
        [out:json][timeout:30];
        (
          node["tourism"~"^({kinds})$"](around:{radius_m},{lat},{lng});
          way["tourism"~"^({kinds})$"](around:{radius_m},{lat},{lng});
          relation["tourism"~"^({kinds})$"](around:{radius_m},{lat},{lng});
        );
        out center tags;
    """


@router.get("/osm/resorts", response_model=OsmPreviewOut)
async def osm_preview_resorts(
    lat: float,
    lng: float,
    radius_km: float = 10.0,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> OsmPreviewOut:
    """Preview resorts/hotels around (lat, lng) within `radius_km` from OSM.

    Free, no API key. Coverage varies by region. Items without a phone number
    are still returned so the admin can see them, but the importer skips them.
    """
    # Overpass handles large radii natively; cap at 200km to avoid pathological
    # full-state scans. (Bumped from 50km — Google has its own per-call cap.)
    radius_m = max(100, min(int(radius_km * 1000), 200_000))
    query = _build_overpass_query(lat, lng, radius_m)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": "b2cagent-admin-import/1.0"},
            )
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Overpass query failed: {e}",
        )

    elements = payload.get("elements", [])
    parsed: list[OsmResort] = []
    for el in elements:
        item = _parse_osm_element(el)
        if item is not None:
            parsed.append(item)

    # Mark which managers already exist (by phone email).
    phones = {p.phone for p in parsed if p.phone}
    if phones:
        emails = {f"{_phone_local_part(p)}@{MANAGER_EMAIL_DOMAIN}" for p in phones}
        existing = (
            await db.scalars(select(User.email).where(User.email.in_(emails)))
        ).all()
        existing_set = set(existing)
        for it in parsed:
            if it.phone:
                e = f"{_phone_local_part(it.phone)}@{MANAGER_EMAIL_DOMAIN}"
                it.manager_exists = e in existing_set

    # De-dup by osm_id (very rare, but happens with mixed node/way membership).
    seen: set[tuple[str, int]] = set()
    deduped: list[OsmResort] = []
    for it in parsed:
        key = (it.osm_type, it.osm_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    # Sort: items with phone first, then by name.
    deduped.sort(key=lambda x: (0 if x.has_phone else 1, x.name.lower()))
    return OsmPreviewOut(items=deduped, total=len(deduped))


class OsmImportSelection(BaseModel):
    items: list[OsmResort]


class OsmImportSummary(BaseModel):
    properties_created: int
    managers_created: int
    skipped_no_phone: int
    skipped_phone_exists: int
    errors: list[ImportRowError]


@router.post("/osm/resorts/import", response_model=OsmImportSummary)
async def osm_import_resorts(
    payload: OsmImportSelection,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> OsmImportSummary:
    """Import selected OSM resorts as draft properties. Each unique phone
    becomes one manager (email `<phone>@b2cagent.xyz`).

    Phone is treated as a hard unique key: if any user (by email or by phone
    column) already has this number, the row is skipped entirely — no new
    manager is made AND no new property is attached. This prevents duplicate
    listings for the same owner from repeat syncs.
    """
    if not payload.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="items is empty"
        )

    properties_created = 0
    managers_created = 0
    skipped_no_phone = 0
    skipped_phone_exists = 0
    errors: list[ImportRowError] = []

    # De-dup within this batch first — same phone in multiple rows = one keeper.
    seen_phones_in_batch: set[str] = set()

    for idx, it in enumerate(payload.items):
        try:
            if not it.has_phone or not it.phone:
                skipped_no_phone += 1
                continue
            phone = it.phone
            email = f"{_phone_local_part(phone)}@{MANAGER_EMAIL_DOMAIN}"

            # Skip duplicates within the same batch.
            if phone in seen_phones_in_batch:
                skipped_phone_exists += 1
                continue

            # Skip if any existing user already has this phone or this email.
            existing = await db.scalar(
                select(User).where(
                    (User.phone == phone) | (User.email == email)
                )
            )
            if existing is not None:
                skipped_phone_exists += 1
                seen_phones_in_batch.add(phone)
                continue

            async with db.begin_nested():
                user = User(
                    email=email,
                    full_name=it.name,
                    phone=phone,
                    role=UserRole.manager,
                    is_active=True,
                    email_verified=False,
                )
                db.add(user)
                await db.flush()
                managers_created += 1
                seen_phones_in_batch.add(phone)

                # B2B/B2C rates aren't in OSM. Seed both to 0 so the admin /
                # manager fills them in before publishing.
                prop = Property(
                    manager_id=user.id,
                    name=it.name,
                    location_text=it.location_text,
                    street=it.street,
                    city=it.city,
                    state=(it.state or "Kerala"),
                    country=(it.country or "India"),
                    lat=it.lat,
                    lng=it.lng,
                    b2b_rate=Decimal("0"),
                    b2c_rate=Decimal("0"),
                    description=(
                        f"Imported from OpenStreetMap ({it.osm_type}/{it.osm_id})."
                        + (f" Website: {it.website}" if it.website else "")
                    ),
                    status=PropertyStatus.draft,
                )
                db.add(prop)
            properties_created += 1
        except Exception as e:  # noqa: BLE001
            errors.append(
                ImportRowError(row_index=idx, message=str(e) or e.__class__.__name__)
            )

    await db.commit()
    return OsmImportSummary(
        properties_created=properties_created,
        managers_created=managers_created,
        skipped_no_phone=skipped_no_phone,
        skipped_phone_exists=skipped_phone_exists,
        errors=errors,
    )


# ---- Google Places (New) sync --------------------------------------------
#
# Same shape as OSM sync so the frontend can switch sources without changing
# its render code. Uses Places API (New) with a field mask so we only pay for
# the fields we actually use (id, name, location, address, phones, website).
# Pricing reference (2024): Nearby Search ≈ $32/1k. The free monthly credit of
# $200 covers ~6k searches — keep an eye on usage if running large radii.

GOOGLE_PLACES_NEARBY_URL = (
    "https://places.googleapis.com/v1/places:searchNearby"
)
GOOGLE_PLACES_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.location",
        "places.formattedAddress",
        "places.addressComponents",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
    ]
)
# All accommodation types we care about from Places API (New) Table A.
# Listed explicitly because `lodging` alone misses places that Google has
# classified more specifically (resort_hotel, farmstay, cottage, etc.).
# Excludes Japan-specific inns and mobile_home/rv_park as irrelevant in IN.
GOOGLE_INCLUDED_TYPES = [
    "lodging",
    "hotel",
    "resort_hotel",
    "guest_house",
    "bed_and_breakfast",
    "hostel",
    "inn",
    "motel",
    "cottage",
    "farmstay",
    "extended_stay_hotel",
    "camping_cabin",
    "campground",
]


def _hash_to_int(s: str) -> int:
    # Stable positive int derived from place_id so OsmResort.osm_id can carry it
    # without colliding across pages.
    return abs(hash(s)) % (10**12)


def _address_component(components: list[dict], type_name: str) -> str | None:
    for c in components or []:
        if type_name in (c.get("types") or []):
            return (
                c.get("longText")
                or c.get("shortText")
                or c.get("long_name")
                or c.get("short_name")
            )
    return None


def _parse_google_place(place: dict) -> OsmResort | None:
    name = (place.get("displayName") or {}).get("text") or place.get(
        "formattedAddress"
    )
    if not name:
        return None
    loc = place.get("location") or {}
    lat = loc.get("latitude")
    lng = loc.get("longitude")
    if lat is None or lng is None:
        return None
    raw_phone = place.get("nationalPhoneNumber") or place.get(
        "internationalPhoneNumber"
    )
    phone = _normalize_phone(raw_phone)
    website = place.get("websiteUri")
    comps = place.get("addressComponents") or []
    street_number = _address_component(comps, "street_number")
    route = _address_component(comps, "route")
    street_parts = [p for p in (street_number, route) if p]
    street = " ".join(street_parts) if street_parts else None
    city = (
        _address_component(comps, "locality")
        or _address_component(comps, "administrative_area_level_2")
    )
    state = _address_component(comps, "administrative_area_level_1")
    country = _address_component(comps, "country")
    location_text = place.get("formattedAddress") or ", ".join(
        p for p in (street, city, state, country) if p
    ) or None
    place_id = place.get("id") or ""
    return OsmResort(
        osm_id=_hash_to_int(place_id),
        osm_type="google",
        name=name,
        phone=phone,
        raw_phone=raw_phone,
        website=website,
        lat=float(lat),
        lng=float(lng),
        street=street,
        city=city,
        state=state,
        country=country,
        location_text=location_text,
        has_phone=phone is not None,
        manager_exists=False,
    )


# Google Nearby Search caps each call at 50km radius and 20 results. To honour
# larger requested radii we tile the area: each tile centre runs its own 50km
# circle, results are merged and de-duped by place_id. Tile spacing (~70km)
# leaves ~30km overlap so the union has no gaps.
GOOGLE_MAX_RADIUS_M = 50_000.0
GOOGLE_TILE_SPACING_KM = 70.0
GOOGLE_TILE_PER_CALL_RADIUS_M = 50_000.0
# Cap the grid so a stray "1000km" request doesn't burn the quota.
GOOGLE_MAX_GRID_SIDE = 7  # → up to 7×7 = 49 calls (~$1.60 at $32/1k)


def _tile_centers(
    lat: float, lng: float, radius_km: float, spacing_km: float
) -> list[tuple[float, float]]:
    """Grid of (lat, lng) tile centres covering a circle of `radius_km`
    around (lat, lng). Adjacent centres are `spacing_km` apart."""
    if radius_km <= GOOGLE_MAX_RADIUS_M / 1000.0:
        return [(lat, lng)]
    n = int(math.ceil(radius_km / spacing_km))
    half = min(n, (GOOGLE_MAX_GRID_SIDE - 1) // 2)
    lat_step = spacing_km / 111.0
    # 1 deg lng shrinks toward the poles; guard against divide-by-zero near them.
    cos_lat = max(0.05, math.cos(math.radians(lat)))
    lng_step = spacing_km / (111.0 * cos_lat)
    return [
        (lat + i * lat_step, lng + j * lng_step)
        for i in range(-half, half + 1)
        for j in range(-half, half + 1)
    ]


async def _google_nearby(
    client: httpx.AsyncClient,
    lat: float,
    lng: float,
    radius_m: float,
) -> tuple[list[dict], str | None]:
    """Single Nearby Search call. Returns (places, error_message)."""
    body = {
        "includedTypes": GOOGLE_INCLUDED_TYPES,
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_m,
            }
        },
    }
    try:
        resp = await client.post(
            GOOGLE_PLACES_NEARBY_URL,
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": settings.GOOGLE_PLACES_API_KEY,
                "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
            },
        )
    except httpx.HTTPError as e:
        return [], f"request failed: {e}"
    if resp.status_code >= 400:
        return [], f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json().get("places", []), None


@router.get("/google/resorts", response_model=OsmPreviewOut)
async def google_preview_resorts(
    lat: float,
    lng: float,
    radius_km: float = 5.0,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> OsmPreviewOut:
    """Preview resorts/hotels around (lat, lng) within `radius_km` from Google
    Places (New). Tiles multiple 50km calls in parallel for larger radii."""
    if not settings.GOOGLE_PLACES_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GOOGLE_PLACES_API_KEY is not configured on the server",
        )

    radius_km = max(0.1, radius_km)
    centers = _tile_centers(lat, lng, radius_km, GOOGLE_TILE_SPACING_KM)

    async with httpx.AsyncClient(timeout=45.0) as client:
        results = await asyncio.gather(
            *[
                _google_nearby(client, c_lat, c_lng, GOOGLE_TILE_PER_CALL_RADIUS_M)
                for c_lat, c_lng in centers
            ]
        )

    errors = [err for _, err in results if err]
    # If every tile failed, surface the first error — otherwise just continue
    # with whatever tiles succeeded.
    if errors and len(errors) == len(results):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Places error: {errors[0]}",
        )

    # De-dupe by place_id across tiles (overlapping circles return duplicates).
    seen_ids: set[str] = set()
    parsed: list[OsmResort] = []
    radius_m = radius_km * 1000.0
    for places, _err in results:
        for p in places:
            pid = p.get("id") or ""
            if pid and pid in seen_ids:
                continue
            seen_ids.add(pid)
            item = _parse_google_place(p)
            if item is None:
                continue
            # Drop anything outside the originally requested radius (overlap
            # from neighbouring tiles can leak in places further than asked).
            d_km = _haversine_km(lat, lng, item.lat, item.lng)
            if d_km * 1000.0 > radius_m:
                continue
            parsed.append(item)

    # Mark already-existing managers — same logic as the OSM endpoint.
    phones = {p.phone for p in parsed if p.phone}
    if phones:
        emails = {f"{_phone_local_part(p)}@{MANAGER_EMAIL_DOMAIN}" for p in phones}
        existing = (
            await db.scalars(select(User.email).where(User.email.in_(emails)))
        ).all()
        existing_set = set(existing)
        for it in parsed:
            if it.phone:
                e = f"{_phone_local_part(it.phone)}@{MANAGER_EMAIL_DOMAIN}"
                it.manager_exists = e in existing_set

    parsed.sort(key=lambda x: (0 if x.has_phone else 1, x.name.lower()))
    return OsmPreviewOut(items=parsed, total=len(parsed))


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))
