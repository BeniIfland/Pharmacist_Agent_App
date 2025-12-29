from __future__ import annotations
from dataclasses import asdict
from typing import Any, Dict, List, Literal, Optional, Tuple
from app.db import MEDICATIONS, Medication
from app.db import BRANCHES, BRANCH_BY_ID, BRANCH_ALIAS_MAP
import re
from app.db import INVENTORY_MAP
from datetime import date
from app.db import RX_BY_ID, MED_BY_ID, USER_BY_ID
from app.db import PRESCRIPTIONS, USER_BY_ID, MED_BY_ID
from datetime import date




ToolStatus = Literal["OK", "NOT_FOUND", "AMBIGUOUS"] #define possible tool outcomes



def _norm(s: str) -> str:
    """
    Normalize text for deterministic matching:
    - lowercase
    - remove punctuation
    - collapse whitespace
    """
    if not s:
        return ""

    s = s.lower()
    # replace any non-letter/digit with space (works for Hebrew too)
    s = re.sub(r"[^\w\u0590-\u05FF]+", " ", s)
    # collapse multiple spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s

def get_medication_by_name(name: str) -> Dict[str, Any]:
    """
    Tool Name: get_medication_by_name
    Resolve a user-provided medication name to a single medication record
    from the synthetic database, with explicit match metadata.

    Purpose:
        Perform a deterministic medication lookup using a canonical display
        name or known aliases. The lookup supports normalization, exact and
        partial matching, and explicit ambiguity handling. This tool is
        designed to ground agent responses in factual data, avoid
        hallucinations, and transparently expose *how* a medication was
        matched (e.g., via alias vs. canonical name).

    Parameters:
        name (str):
            The medication name as provided by the user (e.g. "Ibuprofen",
            "Advil", abbreviations, or partial strings). Matching is
            case-insensitive, ignores leading/trailing whitespace, and uses
            normalized string comparison.

    Matching Strategy:
        The lookup proceeds deterministically in ordered stages:
        1. Exact normalized match:
            - Against canonical display name
            - Against aliases
        2. Contains match (only if no exact matches found):
            - Against canonical display name
            - Against aliases

        For each medication, the first successful match is recorded along
        with metadata describing how the match occurred.

    Returns:
        dict:
            A structured result with a strict schema:
            - status (Literal["OK", "NOT_FOUND", "AMBIGUOUS"]):
                Indicates the outcome of the lookup.
            - matches (list[dict]):
                Present only when status == "AMBIGUOUS". Contains candidate
                medications with:
                    - med_id (str)
                    - display_name (str)
            - medication (dict | None):
                Present only when status == "OK". When present, contains:
                    - med_id (str)
                    - display_name (str)
                    - active_ingredient (str)
                    - rx_required (bool)
                    - label_summary (str)
            - match_info (dict | None):
                Present only when status == "OK". Describes how the match
                was resolved:
                    - input (str):
                        Raw user input.
                    - normalized (str):
                        Normalized form of the input used for matching.
                    - matched_value (str):
                        The canonical name or alias that matched.
                    - matched_kind (Literal["canonical", "alias"]):
                        Whether the match came from the canonical name or
                        an alias.
                    - match_type (Literal["exact", "contains"]):
                        Whether the match was exact or substring-based.

    Error Handling:
        This function does not raise exceptions.
        - If the input is empty or normalizes to an empty string,
          status="NOT_FOUND" is returned.
        - If no medications match, status="NOT_FOUND" is returned with
          empty matches and medication=None.
        - If multiple medications match (e.g., ambiguous abbreviations),
          status="AMBIGUOUS" is returned.

    Fallback Behavior:
        - OK:
            The returned medication record and match_info may be used
            directly by the calling flow to present factual information and
            to explain how the medication was identified (e.g., matched via
            alias).
        - AMBIGUOUS:
            The calling flow should ask the user to clarify which medication
            they intended, using the returned matches, without relying on
            LLM inference.
        - NOT_FOUND:
            The calling flow may request clarification, suggest checking
            spelling or using a generic name, or fall back to a constrained
            general LLM response while explicitly stating that the medication
            was not found in the database.
    """
    q = _norm(name)
    if not q:
        return {"status": "NOT_FOUND", "matches": [], "medication": None} 

    # store tuples: (Medication, matched_value, matched_kind, match_type)
    hits: List[tuple[Medication, str, str, str]] = []

    
   # 1) exact normalized match
    for m in MEDICATIONS:
        candidates = [(m.display_name, "canonical")] + [(a, "alias") for a in m.aliases]
        for val, kind in candidates:
            if _norm(val) == q:
                hits.append((m, val, kind, "exact"))
                break  # stop at first match for this med
    
     # 2) contains match only if no exact matches
    if not hits:
        for m in MEDICATIONS:
            candidates = [(m.display_name, "canonical")] + [(a, "alias") for a in m.aliases]
            for val, kind in candidates:
                if q in _norm(val):
                    hits.append((m, val, kind, "contains"))
                    break

    if not hits:
        return {"status": "NOT_FOUND", "matches": [], "medication": None}

    # de-dupe meds while preserving first match info
    by_id: Dict[str, tuple[Medication, str, str, str]] = {}
    for m, val, kind, mtype in hits:
        if m.med_id not in by_id:
            by_id[m.med_id] = (m, val, kind, mtype)


    # Fallback: in case identified multiple meds e.g. because the user inserted an abbreviation which fits two meds
    # Important for multistep-flow in which the agent clarifies ambiguity with the user intended and avoids LLM inference and potential hallucination
    if len(by_id) > 1:
        return {
            "status": "AMBIGUOUS",
            "matches": [{"med_id": m.med_id, "display_name": m.display_name} for (m, _, _, _) in by_id.values()],
            "medication": None,}
    
    # In case there's a single match
    m, matched_value, matched_kind, match_type = next(iter(by_id.values()))
    return {
        "status": "OK",
        "matches": [],
        "medication": {
            "med_id": m.med_id,
            "display_name": m.display_name,
            "active_ingredient": m.active_ingredient,
            "rx_required": m.rx_required,
            "label_summary": m.label_summary,
        },
        "match_info": {
            "input": (name or ""),
            "normalized": q,
            "matched_value": matched_value,
            "matched_kind": matched_kind,   # "alias" or "canonical"
            "match_type": match_type,       # "exact" or "contains"
        },
    }



def get_branch_by_name(name: str) -> Dict[str, Any]:
    """
    Tool Name: get_branch_by_name
    Resolve a user-provided pharmacy branch name to a single branch record
    from the synthetic database.

    Purpose:
        Perform a deterministic lookup of a pharmacy branch using its
        canonical display name or known aliases (including common
        abbreviations and multilingual variants). This tool enables the
        agent to ground stock-availability responses in factual,
        branch-specific data and avoid hallucinations.

    Parameters:
        name (str):
            The branch name as provided by the user (e.g. "Tel Aviv",
            "TLV", "תל אביב"). Matching is not case-sensitive and is
            resilient to extra whitespace, punctuation, and basic
            formatting differences via normalization.

    Returns:
        dict:
            A structured result with a strict schema:
            - status (Literal["OK", "NOT_FOUND", "AMBIGUOUS"]):
                Indicates the outcome of the lookup.
            - matches (list[dict]):
                Empty unless status == "AMBIGUOUS". When ambiguous, contains
                candidate branches with:
                    - branch_id (str)
                    - display_name (str)
            - branch (dict | None):
                Present only when status == "OK". When present, contains:
                    - branch_id (str)
                    - display_name (str)

    Error Handling:
        This function does not raise exceptions for invalid or missing user
        input. If the input is empty or no matching branch is found, it
        returns status="NOT_FOUND" with empty matches and branch=None.
        If multiple branches match the normalized input, it returns
        status="AMBIGUOUS" with a list of candidate branches.

    Fallback Behavior:
        - OK:
            The returned branch record can be used directly by the calling
            flow to perform branch-specific operations such as inventory
            lookup.
        - AMBIGUOUS:
            The calling flow should ask the user to clarify which branch
            they intended, using the returned matches.
        - NOT_FOUND:
            The calling flow may request clarification, suggest checking
            the branch name or city, or gracefully stop the flow while
            explicitly stating that the branch was not found in the
            database.
    """
    q = _norm(name)
    if not q:
        return {"status": "NOT_FOUND"}

    # Exact alias match
    if q in BRANCH_ALIAS_MAP:
        br_id = BRANCH_ALIAS_MAP[q]
        b = BRANCH_BY_ID[br_id]
        return {"status": "OK", "branch": {"branch_id": b.branch_id, "display_name": b.display_name}}

    # Substring: contains query or query contains name
    matches = []
    for norm_alias, br_id in BRANCH_ALIAS_MAP.items():
        if q in norm_alias or norm_alias in q:
            b = BRANCH_BY_ID[br_id]
            matches.append({"branch_id": b.branch_id, "display_name": b.display_name})

    if len(matches) == 1:
        return {"status": "OK", "branch": matches[0]}
    if len(matches) > 1:
        return {"status": "AMBIGUOUS", "matches": matches}
    return {"status": "NOT_FOUND"}



def get_stock(branch_id: str, med_id: str) -> dict:
    """
    Tool Name: get_stock
    Resolve the stock availability of a specific medication at a specific
    pharmacy branch using a deterministic lookup.

    Purpose:
        Perform a factual, non-probabilistic stock check by querying the
        synthetic inventory map with a (branch_id, med_id) key. This tool
        allows the agent to report medication availability grounded in
        predefined data and prevents speculative or hallucinated answers
        about stock levels.

    Parameters:
        branch_id (str):
            The unique identifier of the pharmacy branch. This value is
            expected to be obtained from a successful call to
            `get_branch_by_name` (status == "OK") and must correspond to a
            known branch in the database.

        med_id (str):
            The unique identifier of the medication. This value is expected
            to be resolved earlier in the flow via a medication extraction
            or lookup step and must correspond to a known medication in the
            database.

    Returns:
        dict:
            A structured result with a strict schema:
            - status (Literal["OK"]):
                Always "OK", indicating the lookup executed successfully.
            - stock_status (str):
                The stock state for the given (branch_id, med_id) pair.
                Possible values depend on the synthetic inventory and may
                include examples such as:
                    - "IN_STOCK"
                    - "OUT_OF_STOCK"
                    - "LOW_STOCK"
                    - "UNKNOWN" (when no explicit record exists)

    Error Handling:
        This function does not raise exceptions and does not return an error
        status. If the (branch_id, med_id) combination is not present in the
        inventory map, the function returns stock_status="UNKNOWN".

    Fallback Behavior:
        - Known stock value:
            The calling flow may present the stock_status directly to the
            user as factual availability information.
        - UNKNOWN:
            The calling flow should explicitly state that stock information
            is unavailable for this medication at the selected branch, and
            may suggest checking another branch or contacting the pharmacy
            directly.
    """
    key = (branch_id, med_id)
    stock = INVENTORY_MAP.get(key, "UNKNOWN")
    return {"status": "OK", "stock_status": stock}



def verify_prescription(rx_id: str) -> dict:
    """
    Tool Name: verify_prescription
    Resolve and validate a prescription record using a deterministic,
    factual-only lookup.

    Purpose:
        Verify whether a prescription exists in the synthetic database and,
        if so, return its key details including medication, patient identity,
        status, and expiration. This tool enables the agent to answer
        prescription-related questions using authoritative data only,
        without interpretation, medical advice, or recommendations.

    Parameters:
        rx_id (str):
            The prescription identifier as provided by the user. The lookup
            is case-insensitive and resilient to leading/trailing
            whitespace. The identifier is normalized to uppercase prior to
            matching.

    Returns:
        dict:
            A structured result with a strict schema:
            - status (Literal["OK", "NOT_FOUND"]):
                Indicates whether the prescription was found.
            - rx (dict | None):
                Present only when status == "OK". When present, contains:
                    - rx_id (str):
                        The prescription identifier.
                    - user_id (str):
                        The unique identifier of the prescription owner.
                    - user_name (str | None):
                        Full name of the user, if available.
                    - med_id (str):
                        The unique identifier of the prescribed medication.
                    - med_name (str | None):
                        Human-readable medication name, if available.
                    - rx_status (Literal["VALID", "EXPIRED", "CANCELLED"]):
                        Final computed prescription status.
                    - expires_on (str):
                        Expiration date in ISO-8601 format (YYYY-MM-DD).

    Status Resolution Rules:
        The returned rx_status is derived deterministically using the
        following rules:
        - If the stored prescription status is "CANCELLED", the final status
          is always "CANCELLED".
        - If the stored status is "EXPIRED" OR the current date is later than
          expires_on, the final status is "EXPIRED".
        - Otherwise, the prescription is considered "VALID".

    Error Handling:
        This function does not raise exceptions.
        - If rx_id is empty, missing, or invalid after normalization,
          status="NOT_FOUND" is returned.
        - If no prescription record exists for the given rx_id,
          status="NOT_FOUND" is returned.

    Fallback Behavior:
        - OK:
            The calling flow may present the prescription details directly
            to the user or continue with prescription-dependent operations
            (e.g., eligibility checks).
        - NOT_FOUND:
            The calling flow should clearly inform the user that the
            prescription could not be found and may suggest verifying the
            prescription ID or contacting the issuing pharmacy or provider.
    """
    # rid = _norm(rx_id)
    if not rx_id:
        return {"status": "NOT_FOUND"}

    p = RX_BY_ID.get(rx_id)
    if not p:
        return {"status": "NOT_FOUND"}
    
    today = date.today()
    is_expired_by_date = today > p.expires_on
    med = MED_BY_ID.get(p.med_id)
    user = USER_BY_ID.get(p.user_id)

    # status rules:
    # - CANCELLED always cancelled
    # - EXPIRED if explicit status EXPIRED OR expired by date
    # - otherwise VALID
    final = p.status
    if p.status != "CANCELLED" and is_expired_by_date:
        final = "EXPIRED" #to verify expired meds which are valid in db but in fact expired 

    return {
        "status": "OK",
        "rx": {
            "rx_id": p.rx_id,
            "user_id": p.user_id,
            "user_name": user.full_name if user else None,
            "med_id": p.med_id,
            "med_name": med.display_name if med else None,
            "rx_status": final,
            "expires_on": p.expires_on.isoformat(),
        },
    }


def get_prescriptions_for_user(user_id: str) -> dict:
    """
    Tool Name: get_prescriptions_for_user
    Resolve and list all prescriptions associated with a specific user
    using a deterministic, factual-only lookup.

    Purpose:
        Retrieve a complete, stable list of prescriptions belonging to a
        single user from the synthetic database. This tool enables the agent
        to answer questions such as “What prescriptions do I have?” or
        “List my active/expired prescriptions” while remaining strictly
        grounded in stored data and avoiding medical interpretation or
        recommendations.

    Parameters:
        user_id (str):
            The unique identifier of the user. The lookup is resilient to
            leading/trailing whitespace and is case-insensitive; the value
            is normalized to lowercase prior to matching.

    Returns:
        dict:
            A structured result with a strict schema:
            - status (Literal["OK", "NOT_FOUND"]):
                Indicates whether the user was found.
            - user (dict | None):
                Present only when status == "OK". Contains:
                    - user_id (str):
                        The normalized user identifier.
                    - user_name (str):
                        The full name of the user.
            - prescriptions (list[dict]):
                Present only when status == "OK". A list of prescription
                records, each containing:
                    - rx_id (str):
                        Prescription identifier.
                    - med_id (str):
                        Medication identifier.
                    - med_name (str | None):
                        Human-readable medication name, if available.
                    - rx_status (Literal["VALID", "EXPIRED", "CANCELLED"]):
                        Final computed prescription status.
                    - expires_on (str):
                        Expiration date in ISO-8601 format (YYYY-MM-DD).

    Status Resolution Rules:
        For each prescription, the returned rx_status is computed
        deterministically using the same logic as `verify_prescription`:
        - If the stored status is "CANCELLED", the final status is
          "CANCELLED".
        - If the stored status is not "CANCELLED" and the current date is
          later than expires_on, the final status is "EXPIRED".
        - Otherwise, the prescription is considered "VALID".

    Error Handling:
        This function does not raise exceptions.
        - If user_id is empty or invalid after normalization,
          status="NOT_FOUND" is returned.
        - If no user record exists for the given user_id,
          status="NOT_FOUND" is returned.

    Determinism Guarantees:
        - The returned list of prescriptions is sorted by rx_id to ensure
          stable ordering across repeated calls with the same data.
        - All status computations are derived solely from stored fields and
          the current date.

    Fallback Behavior:
        - OK:
            The calling flow may present the list of prescriptions directly
            to the user or apply additional filtering (e.g., show only
            VALID prescriptions) at the presentation layer.
        - NOT_FOUND:
            The calling flow should inform the user that no such user was
            found and may request verification of the user identifier or
            terminate the prescription-related flow gracefully.
    
    Returns:
      - {status:"OK", user:{user_id, user_name}, prescriptions:[...]}
      - {status:"NOT_FOUND"}
    """
    uid = (user_id or "").strip().lower()
    if not uid:
        return {"status": "NOT_FOUND"}

    user = USER_BY_ID.get(uid)
    if not user:
        return {"status": "NOT_FOUND"}

    today = date.today()
    out = []
    for p in PRESCRIPTIONS: #can be iptimized using a dedicated index
        if p.user_id.lower() != uid:
            continue

        med = MED_BY_ID.get(p.med_id)
        # Recompute final status same way verify_prescription does based on facts such as the date
        final = p.status
        if p.status != "CANCELLED" and today > p.expires_on:
            final = "EXPIRED"

        out.append({
            "rx_id": p.rx_id,
            "med_id": p.med_id,
            "med_name": med.display_name if med else None,
            "rx_status": final,
            "expires_on": p.expires_on.isoformat(),})

    # sorting (optional)
    out.sort(key=lambda r: r["rx_id"])

    return {
        "status": "OK",
        "user": {"user_id": uid, "user_name": user.full_name},
        "prescriptions": out,}