import enum


class UserRole(str, enum.Enum):
    agent = "agent"
    manager = "manager"
    super_admin = "super_admin"
    both = "both"


class PropertyStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    inactive = "inactive"
    booked = "booked"
    closed = "closed"


class BidStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    withdrawn = "withdrawn"


class PropertyType(str, enum.Enum):
    house = "house"
    flat_apartment = "flat_apartment"
    barn = "barn"
    bed_breakfast = "bed_breakfast"
    boat = "boat"
    cabin = "cabin"
    campervan = "campervan"
    casa_particular = "casa_particular"
    castle = "castle"
    cave = "cave"
    container = "container"
    cycladic_home = "cycladic_home"
    dammuso = "dammuso"
    dome = "dome"
    earth_home = "earth_home"
    farm = "farm"
    guest_house = "guest_house"
    hotel = "hotel"
    houseboat = "houseboat"
    minsu = "minsu"
    riad = "riad"
    ryokan = "ryokan"
    shepherds_hut = "shepherds_hut"
    tent = "tent"
    tiny_home = "tiny_home"
    tower = "tower"
    tree_house = "tree_house"
    trullo = "trullo"
    windmill = "windmill"
    yurt = "yurt"


class PrivacyType(str, enum.Enum):
    entire_place = "entire_place"
    a_room = "a_room"
    shared_room_hostel = "shared_room_hostel"


class LeadStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    won = "won"
    lost = "lost"
    expired = "expired"
