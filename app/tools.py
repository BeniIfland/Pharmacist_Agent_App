from __future__ import annotations
from dataclasses import asdict
from typing import Any, Dict, List, Literal, Optional, Tuple
from app.db import MEDICATIONS, Medication

#TODO: mayabe an additional error is needed
ToolStatus = Literal["OK", "NOT_FOUND", "AMBIGUOUS"] #define possible tool outcomes

def _norm(s: str) -> str:
    """
    Normalization helper to make the name matches not case-sensitive and removing redundant spaces
    
    :param s: user string name
    :type s: str
    :return: normalized name
    :rtype: str
    """
    return "".join(ch.lower() for ch in s.strip())

def get_medication_by_name(name: str) -> Dict[str, Any]:
    """
    Tool Name: get_medication_by_name
    Resolve a user-provided medication name to a single medication record
    from the synthetic database.

    Purpose:
        Perform a deterministic lookup of a medication using its canonical
        name or aliases, supporting basic normalization and
        disambiguation. This tool will be used by the agent to ground responses
        in factual data and avoid hallucinations.

    Parameters:
        name (str):
            The medication name as provided by the user (e.g. "Ibuprofen",
            "Advil"). Matching is not case-sensitive and ignores leading and
            trailing whitespace.

    Returns:
        dict:
            A structured result with a strict schema:
            - status (Literal["OK", "NOT_FOUND", "AMBIGUOUS"]):
                Indicates the outcome of the lookup.
            - matches (list[dict]):
                Empty unless status == "AMBIGUOUS". When ambiguous, contains
                candidate medications with:
                    - med_id (str)
                    - display_name (str)
            - medication (dict | None):
                Present only when status == "OK". When present, contains:
                    - med_id (str)
                    - display_name (str)
                    - active_ingredient (str)
                    - rx_required (bool)
                    - label_summary (str)

    Error Handling:
        This function does not raise exceptions for invalid or missing user
        input. If the input is empty or no medication matches are found,
        it returns status="NOT_FOUND" with empty matches and medication=None.
        Othrwise there is a single match and status is "OK" or there's an ambiguity which will
        be clarified with the user as part of a corresponding multi-step flow.

    Fallback Behavior:
        - OK:
            The returned medication record can be used directly by the
            calling flow to present factual information.
        - AMBIGUOUS:
            The calling flow should ask the user to clarify which medication
            they intended, using the returned matches.
        - NOT_FOUND:
            The calling flow may request clarification, suggest checking the
            spelling or generic name, or fall back to a general LLM response
            while explicitly stating that the medication was not found in
            the database.
    
    """
    q = _norm(name)
    if not q:
        return {"status": "NOT_FOUND", "matches": [], "medication": None} #TODO: this fallback means name was None think if this is the fallback I want - mayabe add a NONE error or something

    matches: List[Medication] = []
    for m in MEDICATIONS: # first check for an exact normalized match 
        candidates = [m.display_name] + m.aliases
        if any(_norm(c) == q for c in candidates):
            matches.append(m)
    
    # Optional
    # fallback: also allow partial contains - to address typos
    # but only compare substrings if no exact match to avoid FPs
    if not matches:
        for m in MEDICATIONS:
            candidates = [m.display_name] + m.aliases
            if any(q in _norm(c) for c in candidates):
                matches.append(m)

    if not matches:
        return {"status": "NOT_FOUND", "matches": [], "medication": None}

    # Fallback: in case identified multiple meds e.g. because the user inserted an abbreviation which fits two meds
    # Important for multistep-flow in which the agent clarifies ambiguity with the user intended and avoids LLM inference and potential hallucination
    if len(matches) > 1:
        return {
            "status": "AMBIGUOUS",
            "matches": [{"med_id": m.med_id, "display_name": m.display_name} for m in matches],
            "medication": None,
        }
    # In case there's a single match
    m = matches[0]
    return {
        "status": "OK",
        "matches": [], #no more than 1 match hence the list can be empty
        "medication": {
            "med_id": m.med_id,
            "display_name": m.display_name,
            "active_ingredient": m.active_ingredient,
            "rx_required": m.rx_required,
            "label_summary": m.label_summary,
        },
    }
