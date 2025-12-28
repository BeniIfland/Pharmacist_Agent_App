from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Literal, Tuple
from datetime import date
from app.utils import norm

#python decorators for simple classes that automatically creates __init__, __eq__ etc.
#good for readability, and for data rather than behavior
@dataclass(frozen=True) #frozen i.e., instances are immutable to maintain stateless deterministic behavior with read only capabilities
class Medication:
    med_id: str
    display_name: str     # name
    aliases: List[str]    # alternative names
    active_ingredient: str
    rx_required: bool
    label_summary: str    # factual label-like summary (no advice)

@dataclass(frozen=True)
class User:
    user_id: str
    full_name: str
    prescriptions: List[str]   # list of med_id user has a prescription for


@dataclass(frozen=True)
class Branch:
    branch_id: str
    display_name: str
    aliases: List[str]

# simple inventory statuses
InventoryStatus = Literal["IN_STOCK", "OUT_OF_STOCK", "LOW_STOCK", "UNKNOWN"]

@dataclass(frozen=True)
class InventoryItem:
    branch_id: str
    med_id: str
    status: InventoryStatus

# Prescription verification: synthetic record the tool can validate
RxStatus = Literal["VALID", "EXPIRED", "CANCELLED"]

@dataclass(frozen=True)
class Prescription:
    rx_id: str
    user_id: str
    med_id: str
    status: RxStatus
    expires_on: date

# synthetic data - located inside the app since it is synthetic, obviously it is not the focus of the assignment to 
# connect the app to an external db

MEDICATIONS: List[Medication] = [
    Medication(
        med_id="med_001",
        display_name="Ibuprofen",
        aliases=["Advil", "Nurofen", "Ibu", "Iboprofen","אדביל","נורופן","איבופרופן","איבו"],  # include common typos
        active_ingredient="Ibuprofen",
        rx_required=False,
        label_summary="Nonsteroidal anti-inflammatory drug (NSAID) used for pain and fever relief.",
    ),
    Medication(
        med_id="med_002",
        display_name="Paracetamol",
        aliases=["Acetaminophen", "Tylenol", "Panadol", "Para","אצטמינופן","טילנול","פנדול","פרצטמול"],
        active_ingredient="Paracetamol (Acetaminophen)",
        rx_required=False,
        label_summary="Analgesic/antipyretic used for pain and fever relief.",
    ),
    Medication(
        med_id="med_003",
        display_name="Amoxicillin",
        aliases=["Amox", "Amoxil","אמוקסילין","אמוקסי","אמוקס"],
        active_ingredient="Amoxicillin",
        rx_required=True,
        label_summary="Penicillin-class antibiotic for bacterial infections.",
    ),
    Medication(
        med_id="med_004",
        display_name="Omeprazole",
        aliases=["Prilosec", "Losec","פרילוסק","לוסק","אומפרזול"],
        active_ingredient="Omeprazole",
        rx_required=False,
        label_summary="Proton pump inhibitor (PPI) that reduces stomach acid.",
    ),
    Medication(
        med_id="med_005",
        display_name="Atorvastatin",
        aliases=["Lipitor", "Atorva","אטורבסטטין","אטורבה","ליפיתור"],
        active_ingredient="Atorvastatin",
        rx_required=True,
        label_summary="Statin medication used to lower LDL cholesterol.",
    ),
]

USERS: List[User] = [
    User(user_id=f"user_{i:03d}", full_name=f"User {i}", prescriptions=[]) for i in range(1, 9)] + [ #first 8 users are without perescribtions
    User(user_id="user_009", full_name="User 9", prescriptions=["med_003"]),  # has Amoxicillin
    User(user_id="user_010", full_name="User 10", prescriptions=["med_005"]), # has Atorvastatin
]

#TODO: check if I ever use them
# helper indices
MED_BY_ID: Dict[str, Medication] = {m.med_id: m for m in MEDICATIONS}
USER_BY_ID: Dict[str, User] = {u.user_id: u for u in USERS}


BRANCHES: List[Branch] = [
    Branch(
        branch_id="br_001",
        display_name="Tel Aviv",
        aliases=["tel aviv", "tlv", "תל אביב", "תא", "ת\"א"], #TODO: check if abbreviations work
    ),
    Branch(
        branch_id="br_002",
        display_name="Jerusalem",
        aliases=["jerusalem", "jlm", "ירושלים", "ם-י", "י\"ם"],#TODO: check if abbreviations work
    ),
    Branch(
        branch_id="br_003",
        display_name="Haifa",
        aliases=["haifa", "חיפה"],
    ),
]

INVENTORY: List[InventoryItem] = [
    # Tel Aviv
    InventoryItem(branch_id="br_001", med_id="med_001", status="IN_STOCK"),   # Ibuprofen
    InventoryItem(branch_id="br_001", med_id="med_002", status="LOW_STOCK"),  # Paracetamol
    InventoryItem(branch_id="br_001", med_id="med_003", status="OUT_OF_STOCK"),# Amoxicillin
    # Jerusalem
    InventoryItem(branch_id="br_002", med_id="med_001", status="OUT_OF_STOCK"),
    InventoryItem(branch_id="br_002", med_id="med_004", status="IN_STOCK"),   # Omeprazole
    InventoryItem(branch_id="br_002", med_id="med_005", status="IN_STOCK"),   # Atorvastatin
    # Haifa
    InventoryItem(branch_id="br_003", med_id="med_002", status="IN_STOCK"),
    InventoryItem(branch_id="br_003", med_id="med_004", status="LOW_STOCK"),
]

PRESCRIPTIONS: List[Prescription] = [
    Prescription(rx_id="RX-10001", user_id="user_009", med_id="med_003", status="VALID",   expires_on=date(2026, 3, 1)),
    Prescription(rx_id="RX-10002", user_id="user_010", med_id="med_005", status="VALID",   expires_on=date(2026, 1, 15)),
    Prescription(rx_id="RX-10003", user_id="user_009", med_id="med_003", status="EXPIRED", expires_on=date(2024, 12, 1)),
    Prescription(rx_id="RX-10004", user_id="user_001", med_id="med_001", status="CANCELLED", expires_on=date(2026, 12, 31)),
    Prescription(rx_id="RX-10006", user_id="user_010", med_id="med_005", status="EXPIRED", expires_on=date(2025, 1, 1)),
]

#TODO: check if I ever use them

BRANCH_BY_ID: Dict[str, Branch] = {b.branch_id: b for b in BRANCHES}
RX_BY_ID: Dict[str, Prescription] = {p.rx_id.upper(): p for p in PRESCRIPTIONS}

# lookup maps
BRANCH_ALIAS_MAP: Dict[str, str] = {
    norm(alias): b.branch_id
    for b in BRANCHES
    for alias in ([b.display_name] + b.aliases)
}

# inventory map for O(1) lookup
INVENTORY_MAP: Dict[Tuple[str, str], InventoryStatus] = {
    (i.branch_id, i.med_id): i.status for i in INVENTORY}
