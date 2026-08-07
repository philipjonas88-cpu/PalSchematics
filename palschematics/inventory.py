"""Players, item containers and the rules for putting schematics into them.

Item slots inside ``worldSaveData.ItemContainerSaveData`` are stored as opaque
byte blobs. In Palworld 1.0 one slot is::

    <u32 slot_index><u32 stack_count><u32 str_len><static_id + NUL><52 zero bytes>

Only occupied slots are stored, each carrying its own index, so adding an item
means appending one slot struct at a free index below the container's SlotNum.
The 52-byte trailer holds per-instance data (dynamic item ids, durability) and
is all-zero for plain stackable items such as schematics.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

TRAILER_LEN = 52
CONTAINER_FIELDS = (
    "CommonContainerId",
    "EssentialContainerId",
    "WeaponLoadOutContainerId",
    "PlayerEquipArmorContainerId",
    "FoodEquipContainerId",
    "DropSlotContainerId",
)


class InventoryError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# slots
# --------------------------------------------------------------------------
@dataclass
class Slot:
    index: int
    count: int
    static_id: str
    trailer: bytes

    @property
    def is_plain(self) -> bool:
        """No per-instance data -- safe to reason about as a simple stack."""
        return not any(self.trailer)


def parse_slot(values) -> Slot:
    b = bytes(values)
    if len(b) < 12:
        raise InventoryError("item slot blob is too short")
    index, count, str_len = struct.unpack("<III", b[:12])
    if str_len > len(b) - 12:
        raise InventoryError("item slot blob has a bad string length")
    static_id = b[12:12 + str_len].split(b"\x00")[0].decode("utf-8", "replace")
    return Slot(index, count, static_id, b[12 + str_len:])


def build_slot(index: int, count: int, static_id: str) -> list[int]:
    name = static_id.encode("utf-8") + b"\x00"
    blob = struct.pack("<III", index, count, len(name)) + name + bytes(TRAILER_LEN)
    return list(blob)


def _array_prop(values):
    return {"array_type": "ByteProperty", "id": None,
            "value": {"values": values}, "type": "ArrayProperty"}


# --------------------------------------------------------------------------
# containers
# --------------------------------------------------------------------------
@dataclass
class Container:
    guid: str
    entry: dict

    @property
    def slot_num(self) -> int:
        return self.entry["value"]["SlotNum"]["value"]

    @property
    def _slot_list(self) -> list:
        return self.entry["value"]["Slots"]["value"]["values"]

    def slots(self) -> list[Slot]:
        return [parse_slot(s["RawData"]["value"]["values"]) for s in self._slot_list]

    def used_indices(self) -> set[int]:
        return {s.index for s in self.slots()}

    def free_indices(self) -> list[int]:
        used = self.used_indices()
        return [i for i in range(self.slot_num) if i not in used]

    def contains(self, static_id: str) -> bool:
        return any(s.static_id == static_id for s in self.slots())

    def add(self, static_id: str, count: int, index: int) -> None:
        if index >= self.slot_num:
            raise InventoryError(
                f"slot {index} is past this container's capacity ({self.slot_num})")
        if index in self.used_indices():
            raise InventoryError(f"slot {index} is already occupied")
        template = self._slot_list[0] if self._slot_list else None
        if template is None:
            raise InventoryError(
                "cannot add to a completely empty container -- put one item in it "
                "in-game first so the save has a slot to copy version data from")
        self._slot_list.append({
            "RawData": _array_prop(build_slot(index, count, static_id)),
            "CustomVersionData": _array_prop(list(template["CustomVersionData"]["value"]["values"])),
        })
        self._slot_list.sort(key=lambda s: parse_slot(s["RawData"]["value"]["values"]).index)


def containers_by_guid(save) -> dict[str, Container]:
    out = {}
    for entry in save.world["ItemContainerSaveData"]["value"]:
        guid = str(entry["key"]["ID"]["value"])
        out[guid] = Container(guid, entry)
    return out


# --------------------------------------------------------------------------
# players
# --------------------------------------------------------------------------
@dataclass
class Player:
    name: str
    uid: str
    level: int | None
    sav_path: str | None = None
    container_ids: dict = field(default_factory=dict)

    @property
    def backpack_id(self) -> str | None:
        return self.container_ids.get("CommonContainerId")

    def label(self) -> str:
        lvl = f"Lv {self.level}" if self.level else "Lv ?"
        return f"{self.name}  ({lvl})"


def _uid_to_filename(uid: str) -> str:
    return uid.replace("-", "").upper() + ".sav"


def find_players(save, players_dir: str | None = None) -> list[Player]:
    """Every player character in the world, newest-looking first.

    Names live in Level.sav; container ids live in each Players/<uid>.sav, so
    both are read. A player whose .sav is missing is still listed (without
    containers) rather than silently dropped.
    """
    from . import saveio

    players: list[Player] = []
    for entry in save.world["CharacterSaveParameterMap"]["value"]:
        params = entry["value"]["RawData"]["value"]["object"]["SaveParameter"]["value"]
        if not params.get("IsPlayer", {}).get("value"):
            continue
        uid = str(entry["key"]["PlayerUId"]["value"])
        lvl = params.get("Level", {}).get("value")
        if isinstance(lvl, dict):
            lvl = lvl.get("value")
        players.append(Player(
            name=params.get("NickName", {}).get("value") or "(unnamed)",
            uid=uid,
            level=lvl,
        ))

    if players_dir and os.path.isdir(players_dir):
        for p in players:
            path = os.path.join(players_dir, _uid_to_filename(p.uid))
            if not os.path.exists(path):
                continue
            p.sav_path = path
            try:
                psav = saveio.Save.load(path, custom={})
            except Exception:  # noqa: BLE001 - a broken player file must not hide the rest
                continue
            data = psav.gvas.properties.get("SaveData", {}).get("value", {})
            inv = data.get("InventoryInfo") or data.get("inventoryInfo")
            if not inv:
                continue
            for key, val in inv["value"].items():
                if isinstance(val, dict) and val.get("struct_type") == "PalContainerId":
                    p.container_ids[key] = str(val["value"]["ID"]["value"])

    players.sort(key=lambda p: (-(p.level or 0), p.name.lower()))
    return players


# --------------------------------------------------------------------------
# the safety policy
# --------------------------------------------------------------------------
@dataclass
class Policy:
    """Guard rails for writing into a player's backpack.

    The batch size follows the container: you can add as many schematics as
    there are free slots, minus ``reserve_slots`` kept empty. A completely full
    Palworld inventory is where odd behaviour (items landing on the ground,
    pickups vanishing) tends to happen, so the bag is never filled to the brim.

    ``max_per_apply`` is an optional hard ceiling on top of that; 0 means no
    ceiling, which is the default.
    """
    enabled: bool = True
    reserve_slots: int = 5
    max_per_apply: int = 0

    def budget(self, free_slots: int) -> int:
        """How many items may go in, given this many free slots."""
        if not self.enabled:
            return free_slots
        room = max(0, free_slots - self.reserve_slots)
        return min(room, self.max_per_apply) if self.max_per_apply else room

    def describe(self, free_slots: int | None = None) -> str:
        if not self.enabled:
            base = "Safety limits OFF - the container's capacity is the only limit."
        else:
            base = (f"Safe mode: fills the free slots but always leaves "
                    f"{self.reserve_slots} empty.")
            if self.max_per_apply:
                base += f" Never more than {self.max_per_apply} per apply."
        if free_slots is not None:
            base += f"\nRoom for {self.budget(free_slots)} right now."
        return base


@dataclass
class Plan:
    """What an apply would do. Nothing is written until this is executed."""
    container: Container
    to_add: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    over_limit: list[str] = field(default_factory=list)
    no_space: list[str] = field(default_factory=list)
    blocked: str | None = None

    @property
    def ok(self) -> bool:
        return self.blocked is None and bool(self.to_add)

    def summary(self) -> str:
        bits = [f"{len(self.to_add)} to add"]
        if self.already_present:
            bits.append(f"{len(self.already_present)} already owned")
        if self.over_limit:
            bits.append(f"{len(self.over_limit)} over the per-apply limit")
        if self.no_space:
            bits.append(f"{len(self.no_space)} with no free slot")
        return ", ".join(bits)


def plan_add(container: Container, codes: list[str], policy: Policy) -> Plan:
    """Work out exactly which codes can go in, and why the others cannot."""
    plan = Plan(container=container)
    free = container.free_indices()

    wanted = []
    for code in codes:
        if container.contains(code):
            plan.already_present.append(code)
        else:
            wanted.append(code)

    if policy.enabled and len(free) <= policy.reserve_slots:
        plan.blocked = (
            f"Not enough room: {len(free)} free slot(s), and safe mode keeps "
            f"{policy.reserve_slots} free.\n\nMake space in the backpack in-game "
            f"(or turn safety limits off, at your own risk)."
        )
        return plan
    if not free:
        plan.blocked = "That container is completely full."
        return plan

    budget = policy.budget(len(free))
    plan.to_add = wanted[:budget]
    rest = wanted[budget:]
    if rest:
        if policy.enabled and policy.max_per_apply and len(plan.to_add) == policy.max_per_apply:
            plan.over_limit = rest
        else:
            plan.no_space = rest
    return plan


def execute(plan: Plan, count: int = 1) -> list[tuple[str, int]]:
    """Apply a plan to the in-memory save. Returns [(code, slot_index)]."""
    if plan.blocked:
        raise InventoryError(plan.blocked)
    placed = []
    for code in plan.to_add:
        free = plan.container.free_indices()
        if not free:
            raise InventoryError("ran out of free slots while applying")
        index = free[0]
        plan.container.add(code, count, index)
        placed.append((code, index))
    return placed
