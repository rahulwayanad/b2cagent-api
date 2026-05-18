"""Reference catalogs for property types, privacy types, and the canonical
list of property fields the super admin can toggle.

Static data — no DB. Exposed via /api/v1/property-types, /privacy-types,
and seeded into the field_configs table on migration.
"""
from __future__ import annotations

from typing import TypedDict

from app.models.enums import PrivacyType, PropertyType


class CatalogEntry(TypedDict):
    value: str
    label: str
    icon_key: str


class PrivacyEntry(TypedDict):
    value: str
    label: str
    description: str
    icon_key: str


PROPERTY_TYPE_CATALOG: list[CatalogEntry] = [
    {"value": PropertyType.house.value, "label": "House", "icon_key": "home"},
    {"value": PropertyType.flat_apartment.value, "label": "Flat/apartment", "icon_key": "building"},
    {"value": PropertyType.barn.value, "label": "Barn", "icon_key": "warehouse"},
    {"value": PropertyType.bed_breakfast.value, "label": "Bed & breakfast", "icon_key": "coffee"},
    {"value": PropertyType.boat.value, "label": "Boat", "icon_key": "anchor"},
    {"value": PropertyType.cabin.value, "label": "Cabin", "icon_key": "tent-tree"},
    {"value": PropertyType.campervan.value, "label": "Campervan/motorhome", "icon_key": "caravan"},
    {"value": PropertyType.casa_particular.value, "label": "Casa particular", "icon_key": "house"},
    {"value": PropertyType.castle.value, "label": "Castle", "icon_key": "castle"},
    {"value": PropertyType.cave.value, "label": "Cave", "icon_key": "mountain"},
    {"value": PropertyType.container.value, "label": "Container", "icon_key": "package"},
    {"value": PropertyType.cycladic_home.value, "label": "Cycladic home", "icon_key": "home"},
    {"value": PropertyType.dammuso.value, "label": "Dammuso", "icon_key": "home"},
    {"value": PropertyType.dome.value, "label": "Dome", "icon_key": "circle"},
    {"value": PropertyType.earth_home.value, "label": "Earth home", "icon_key": "globe"},
    {"value": PropertyType.farm.value, "label": "Farm", "icon_key": "tractor"},
    {"value": PropertyType.guest_house.value, "label": "Guest house", "icon_key": "key-round"},
    {"value": PropertyType.hotel.value, "label": "Hotel", "icon_key": "hotel"},
    {"value": PropertyType.houseboat.value, "label": "Houseboat", "icon_key": "sailboat"},
    {"value": PropertyType.minsu.value, "label": "Minsu", "icon_key": "home"},
    {"value": PropertyType.riad.value, "label": "Riad", "icon_key": "home"},
    {"value": PropertyType.ryokan.value, "label": "Ryokan", "icon_key": "home"},
    {"value": PropertyType.shepherds_hut.value, "label": "Shepherd's hut", "icon_key": "tent"},
    {"value": PropertyType.tent.value, "label": "Tent", "icon_key": "tent"},
    {"value": PropertyType.tiny_home.value, "label": "Tiny home", "icon_key": "home"},
    {"value": PropertyType.tower.value, "label": "Tower", "icon_key": "tower-control"},
    {"value": PropertyType.tree_house.value, "label": "Tree house", "icon_key": "trees"},
    {"value": PropertyType.trullo.value, "label": "Trullo", "icon_key": "home"},
    {"value": PropertyType.windmill.value, "label": "Windmill", "icon_key": "fan"},
    {"value": PropertyType.yurt.value, "label": "Yurt", "icon_key": "circle"},
]


PRIVACY_TYPE_CATALOG: list[PrivacyEntry] = [
    {
        "value": PrivacyType.entire_place.value,
        "label": "An entire place",
        "description": "Guests have the whole place to themselves.",
        "icon_key": "home",
    },
    {
        "value": PrivacyType.a_room.value,
        "label": "A room",
        "description": "Guests have their own room in a home, plus access to shared spaces.",
        "icon_key": "door-open",
    },
    {
        "value": PrivacyType.shared_room_hostel.value,
        "label": "A shared room in a hostel",
        "description": "Guests sleep in a shared room in a professionally managed hostel with staff on-site 24/7.",
        "icon_key": "users",
    },
]


# Fields the super admin can hide/show on the property entity. The migration
# seeds one FieldConfig row per name with visible=True, required=False.
PROPERTY_FIELDS: list[str] = [
    "name",
    "description",
    "location_text",
    "lat",
    "lng",
    "b2b_rate",
    "b2c_rate",
    "property_type",
    "privacy_type",
    "guests",
    "bedrooms",
    "beds",
    "bathrooms",
    "min_guests",
    "max_guests",
]


FIELD_CONFIG_ENTITIES: dict[str, list[str]] = {
    "property": PROPERTY_FIELDS,
}
