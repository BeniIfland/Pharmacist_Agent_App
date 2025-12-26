from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional

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

# helper indices
MED_BY_ID: Dict[str, Medication] = {m.med_id: m for m in MEDICATIONS}
USER_BY_ID: Dict[str, User] = {u.user_id: u for u in USERS}
