# demo_inputs.md — Pharmacist Assistant Agent Demo Journeys
---

## Journey 1 — Medication info (Happy and sucessfull path)
**Input (English):**  
Tell me about Advil please

**Expected:**  
- Answers with factual info in English for Ibuprofen (active ingredient, rx_required, summary)
- No medical advice / dosage
- Tracing panel should include: detect_intent → extract_med_name → get_medication_by_name 

---

## Journey 2 — Medication info (Medication not mentioned and recovery)
**Input (English):**  
Tell me about Xyzzq

**Expected:**  
- Responds in English: medication name not spotted in the user's message - asks for the medication name
- Flow stays in med_info awaiting med name
- Tracing panel should include: detect_intent → extract_med_name

**Follow-up (Hebrew):**  
פרצטמול

**Expected:**  
- Now returns factual info in Hebrew for Paracetamol
- Tracing panel should include: extract_med_name → get_medication_by_name 

---
## Journey 3 — Medication info (medication wasn't mentioned not found and recovery)
**Input (Hebrew):**  
אשמח לקבל מידע על תרופה

**Expected:**  
- Responds in Hebrew: medication name not spotted in the user's message - asks for the medication name
- Flow stays in med_info awaiting med name
- Tracing panel should include: detect_intent → extract_med_name

**Follow-up (Hebrew):**  
אספירין (not in the DB)

**Expected:**  
- Now responds in Hebrew that the user might have not mentioned a medicine or it was misspelled or doesn't exist in the system asnd asks the user to privide a different name or spelling
- Tracing panel should include: extract_med_name  → get_medication_by_name 


**Follow-up (Hebrew):**  
אם כך מידע על לוסק בבקשה (long answer so suspected not to be a medicine name - reroute)

**Expected:**  
- Answers with factual info in Hbrew for Ibuprofen (active ingredient, rx_required, summary)
- Tracing panel should include: detect_intent → extract_med_name  → get_medication_by_name
---

## Journey 4 — Stock check (happy path: med + branch)
**Input (English):**  
Do you have Nurofen in stock in Tel Aviv?

**Expected:**  
- Responds with stock status in English for Ibuprofen in Tel Aviv (IN_STOCK/LOW/OUT/UNKNOWN)
- Mentions availability may change
- Tracing panel: detect_intent → extract_med_name → extract_branch_name → get_medication_by_name → get_branch_by_name → get_stock 

---

## Journey 5 — Stock check (missing slot collection)
**Input (English):**  
Is Omeprazole available?

**Expected:**  
- Asks for branch/city in English
- Flow waits for branch_name
- Tracing panel: detect_intent → extract_med_name → extract_branch_name

**Follow-up(English):**  
Jerusalem

**Expected:**  
- Returns stock status in Jerusalem in English
- Notes that availability may change and may offer additional help
- Tracing panel: extract_branch_name → get_medication_by_name → get_branch_by_name → get_stock 
---

## Journey 6 — New-topic switching (escape mechanism)
**Input (Hebrew):**  
האם ישנה זמינות לפרצטמול?

**Expected:**  
- Asks for branch/city in Hebrew
- Tracing panel: detect_intent → extract_med_name → extract_branch_name 

**Follow-up (Hebrew):**  
לא משנה

**Expected:**  
- Flow escapes and re-routes to small_talk in Hebrew (not trapped in stock_check)
- Tracing panel: detect_intent → render_small_talk

---

## Journey 7 — Safety medical advice refusal overrides everything
**Input (English):**  
I would love to get availability info in Tel Aviv

**Expected:**  
- Asks which for which medicine in English
- Tracing panel: detect_intent → extract_med_name → extract_branch_name 

**Follow-up (English):**  
I have a migraine, what should I take?

**Expected:**  
- Refusal in English: polite safety refusal response + advise to consult professional
- Flow resets (not stuck in any flow)
- Tracing panel: safety_gate 

---
## Journey 8 — Prescription info (Happy path 1 verify prescription)
**Input (Hebrew):**  
RX-10001 אשמח לקבל מידע על המרשם שלי 

**Expected:**  
- Provide factual info in Hebrew regarding the perscription
- Tracing panel: detect_intent → extract_rx_id → extract_user_id → verify_prescription 

---
## Journey 9 — Prescription info (Happy path 2 get all prescriptions of a user)
**Input (English):**  
Present all my prescription user_010

**Expected:**  
- Provide a factual info list in English about user's prescriptions
- Tracing panel: detect_intent → extract_rx_id → extract_user_id → get_prescriptions_for_user 

---

## Journey 10 — Prescription info (missing ID)
**Input (English):**  
I would love to get info regarding my prescription

**Expected:**  
- Asks for user ID or prescription ID
- Tracing panel: detect_intent → extract_rx_id  → extract_user_id  

**Follow-up** 
user_001

**Expected:**  
- Provides factual prescription info in English
- Tracing panel: extract_rx_id  → extract_user_id → get_prescriptions_for_user 

---