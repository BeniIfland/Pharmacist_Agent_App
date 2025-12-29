import os
from openai import OpenAI
from dotenv import load_dotenv
from typing import Iterator
from app.intent import IntentResult
import json
import re


load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)

def _extract_json_object(text: str) -> str:
    """
    Extract the first JSON object from text (in case the model adds extra whitespace).
    """
    m = _JSON_OBJ_RE.search(text.strip())
    if not m:
        raise ValueError(f"Flow router did not return JSON. Got: {text!r}")
    return m.group(0)


def detect_intent_llm(text: str) -> IntentResult:
    resp = client.responses.create(
        model="gpt-5",
        reasoning={"effort": "minimal"},
        max_output_tokens=120,
        input=(
            "You are an intent router for a Pharmacist Assistant.\n"
            "Your goal is to return a JSON which classifies user's intent."
            "Return ONLY a valid JSON and nothing else.\n\n"
            "Allowed intents:\n"
            "- med_info: the user asks about a medication name or information AVOID confusing when he asks for a medical advice or guidance unrelated to specific medicines.\n"
            "- stock_check: the user asks if a medication is available or in stock in a branch/city/store.\n"
            "- rx_verify: the user asks to verify his prescription or get a list of his prescriptions\n"
            "- small_talk: greetings, thanks, 'what can you do', casual chit-chat, any message that is not related to specific medicines, including sales, encouragments or a behavior that is unsafe for the customer or that out of the scope of a Pharmacist Assistant chatbot or that is not covered by the aforementioned intents.\n"
            "Language:\n"
            "- lang must be 'he' if the user wrote in Hebrew letters, else 'en'.\n\n"
            "JSON schema:\n"
            "{\n"
            '  "intent": "med_info|small_talk|rx_verify|stock_check",\n'
            '  "confidence": <a float [0,1] that express your confidence in the decision>,\n' #debugging,evaluation,future fuardrail
            '  "lang": "he|en",\n'
            '  "notes": <a short description on why you chose this intent>\n' #debugging and evaluation
            "}\n\n"
            f"User message:\n{text}"
        ),)
    
    raw = resp.output_text or ""
    json_str = _extract_json_object(raw)
    data = json.loads(json_str)

    # Validate using Pydantic
    return IntentResult.model_validate(data)

#Not used, most basic LLM query
def qury_llm(message: str) -> str:  #not good for streaming
    response = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "user", "content": message}])
    return response.choices[0].message.content


#not used basic stream query
def stream_llm(message: str):

    with client.responses.stream(model="gpt-5",input=message, #most LLM responses are cotrolled and broken down by the flow - hence a small version is better and faster
            reasoning={"effort": "minimal"},  max_output_tokens=160   
                                 ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta #generator to enable streaming | its good to avoid async for etc....


# class MedicineExtraction(BaseModel):
#     medicine: Optional[str]


def extract_med_name(text: str) -> str | None:
    """
    Extract medicine name out of user provided text    
    :param text: 
    :type text: str
    :return: 
    :rtype: str | None
    """
    resp = client.responses.create(
        model="gpt-5",
        input=[
            {
                "role": "system",
                "content": (
                    "You are a professional entity extractor specializing in medicine names.\n"
                    "User language can be Hebrew or English"
                    "Your task:\n"
                    "1. Read the user's text carefully.\n"
                    "2. Identify the name of the medicine mentioned.\n"
                    "3. Return ONLY the medicine name in the same language it was written.\n"
                    "4. You are allowed to correct a spelling mistake ONLY if you are sure that is the case.\n"
                    "5. If no medicine is identified, return null.\n"
                    "\n"
                    "Examples:\n"
                    "Input: tell me about aspirin\n"
                    "Output: aspirin\n"
                    "\n"
                    "Input: tell me about Hindu history\n"
                    "Output: null\n"
                    "\n"
                    "Input: אדביל\n"
                    "Output: אדביל\n"
                    "\n"
                    "Input: ןאדביל\n"
                    "Output: אדביל\n"
                ),
            },
            {
                "role": "user",
                "content": text,
            },
        ],
        reasoning={"effort": "minimal"},
        max_output_tokens=30,)

    out = (resp.output_text or "").strip()
    if out.upper() == "NULL" or out == "":
        return None
    return out




client = OpenAI()

def render_text_stream(lang: str, instruction: str, facts: str) -> Iterator[str]:
    """ 
    Stream a strictly factual UI response in the user's language.
    :param lang: user used language
    :type lang: str
    :param instruction: current flow-step instructions
    :type instruction: str
    :param facts: factual info necessary to generate llm response based on
    :type facts: str
    :return: streamed text iterator
    :rtype: str | None
    """
    language = "Hebrew" if lang == "he" else "English"

    prompt = f"""
You are a pharmacist assistant UI text generator.

Rules:
- You are allowed to respond ONLY in English or Hebrew, and you can say these are the only languages you speak if addressed in another.
- This time reply in {language} and make sure to present the facts in this language.
- Use ONLY the facts provided provided to generate your response. Do not add medical advice, diagnosis, dosage, recommendations, or purchase encouragement from your prior knowledge.
- If the user asks for advice, refuse briefly and suggest consulting a pharmacist/doctor (in the same language).
- Keep it concise (3-6 lines) but always include a relevant into to make your reply sound human for smooth user experience".
- If you are missing a required fact, ask a short clarifying question.
- You HAVE to follow the following instruction:

Instruction:
{instruction}

Facts:
{facts}
""".strip()

    with client.responses.stream(
        model="gpt-5",
        input=prompt,
        reasoning={"effort": "minimal"},
        max_output_tokens=160, #limiting the model for UX and avoid hallucinations and be token efficient
        ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta

#med_info renderers

def render_med_info_stream(lang: str, med: dict, match_info: dict | None) -> Iterator[str]:
    """
    Renders medicine info facts
    
    :param lang: user detected language
    :type lang: str
    :param med: medicine info
    :type med: dict
    :return: streamed text iterator
    :rtype: Iterator[str]
    """
    instruction = "Present factual medication information and a brief safety note."
    facts_lines = [
        f'Name (Official): {med["display_name"]}',
        f'Active ingredient: {med["active_ingredient"]}',
        f'Prescription required: {med["rx_required"]}',
        f'Summary: {med["label_summary"]}',
    ]

    # Adding alias clarification only if tool told us it was an alias hit
    if match_info and match_info.get("matched_kind") == "alias":
        alias = match_info.get("matched_value") or match_info.get("input") or ""
        match_type = match_info.get("match_type") or ""
        # Keep it purely factual: "user input matched alias"
        facts_lines.append(
            f'User input was: "{alias}", let him know he sees {med["display_name"]} abecause it matched an alias"'
            # + (f' (match_type={match_type}).' if match_type else ".")
        )

    facts = "\n".join(facts_lines)
    return render_text_stream(lang, instruction, facts)


def render_ambiguous_stream(lang: str, options: list[str]) -> Iterator[str]:
    """
    Renders clarifying ambiguity instructions
    
    :param lang: user detected language
    :type lang: str
    :param options: detected options to clear ambiguity from
    :type options: list[str]
    :return: streamed text iterator
    :rtype: Iterator[str]
    """
    instruction = "Ask the user which medication they meant from the options."
    facts = "Options: " + ", ".join(options)
    return render_text_stream(lang, instruction, facts)


def render_not_found_stream(lang: str) -> Iterator[str]:
    """
    Render the instruction of the not found medicine step
    
    :param lang: user detected language
    :type lang: str
    :return: streamed text iterator
    :rtype: Iterator[str]
    """
    instruction = "Inform the user that you couldn't find the medication bceause of misspelling or it doesn't exist in the system, ask for a different name or spelling."
    facts = "no medication found"
    return render_text_stream(lang, instruction, facts)


def render_ask_med_name_stream(lang: str) -> Iterator[str]:
    """
    Render instructions to clarify the medicine name
    
    :param lang: user detected language
    :type lang: str
    :return: streamed text iterator
    :rtype: Iterator[str]
    """
    instruction = "Ask the user to provide the medication name."
    facts = "Missing: medication name"
    return render_text_stream(lang, instruction, facts)


def render_small_talk_stream(lang: str, user_text: str):
    instruction = (
        "You are a Pharmacist Assistant, respond politely to small talk and greeting."
        "You should greet, thank, and MAY BUT NOT HAVE TO explain your capabilities. "
        "DO NOT provide medical advice, diagnosis, or recommendations."
        "And you are NOT allowed to talk about inventory, ot prescriptions.")
    facts = (
        f"User said: {user_text}\n"
        # "Capabilities: factual medication info, availability, prescription requirement.\n"
        # "If user asks for personal guidance: suggest consulting a pharmacist/doctor."
        )
    return render_text_stream(lang, instruction, facts)

def render_refusal_stream(lang: str, user_text: str):
    instruction = (
        "Refuse to provide medical advice/diagnosis/recommendations. "
        "Explain you can provide factual medication info only. "
        "Suggest consulting a pharmacist/doctor for personal guidance."
    )
    facts = f"User request: {user_text}"
    return render_text_stream(lang, instruction, facts)

#stock_check renderers:

def render_stock_check_stream(lang: str, med: dict, branch: dict, stock_status: str, match_info: dict | None):
    # med is Medication dict from tool_result["medication"]
    # branch is {"branch_id":..., "display_name":...} from get_branch_by_name
    instructions = (
        "You are a pharmacist assistant. Provide factual stock availability only.\n"
        "No advice, no recommendations, no dosage, no diagnosis.\n"
        "Do not encourage purchase.\n"
        "Point out that availability may change and offer additional help.\n"
        "NEVER offer additional help\n"
        "Keep it short.\n")
    facts_lines = [
        f'Branch: {branch["display_name"]}',
        f'Medication (canonical): {med["display_name"]}',
        f'Stock status: {stock_status}',]

    if match_info and match_info.get("matched_kind") == "alias":
        alias = match_info.get("matched_value") or match_info.get("input") or ""
        facts_lines.append(
            f'User input was: "{alias}", let him know he sees {med["display_name"]} abecause it matched an alias"'
        )

    facts = "\n".join(facts_lines)
    return render_text_stream(lang, instructions, facts)  


def render_ask_branch_stream(lang: str) -> Iterator[str]: #simple - can be replaced by the LLM - based render_text_stream
    text = "באיזה סניף מדובר? (למשל תל אביב / ירושלים / חיפה)" if lang == "he" else \
           "Which branch/city? (e.g., Tel Aviv / Jerusalem / Haifa)"
    yield text

 #simple - can be replaced by the LLM - based render_text_stream
def render_ask_med_and_branch_stream(lang: str) -> Iterator[str]:
    text = "לאילו תרופה וסניף התכוונת?" if lang == "he" else "Which medication and branch/city did you mean?"
    yield text

 #simple - can be replaced by the LLM - based render_text_stream
def render_ambiguous_branch_stream(lang: str, options: list[str]) -> Iterator[str]:
    if lang == "he":
        yield "למה התכוונת? ציין רק אחד בבקשה:\n- " + "\n- ".join(options)
    else:
        yield "Which one did you mean? Pick one please:\n- " + "\n- ".join(options)

 #simple - can be replaced by the LLM - based render_text_stream
def render_branch_not_found_stream(lang: str) -> Iterator[str]:
    if lang == "he":
        yield "לצערי לא מצאתי את הסניף הזה אולי אין לנו סניף במקום המדובר או שישנה טעות באיות. אפשר לכתוב עיר/סניף כמו: תל אביב / ירושלים / חיפה."
    else:
        yield "Unfortunately I couldn’t find that branch, maybe we don't have a branch in this location or you had a spelling mistake. Try a city/branch like: Tel Aviv / Jerusalem / Haifa."


# prescriptions flow renderers:

 #simple - can be replaced by the LLM - based render_text_stream
def render_ask_rx_or_user_stream(lang: str) -> Iterator[str]:
    if lang == "he":
        yield "כדי לבדוק מרשם, כתבי מזהה מרשם (למשל RX-10001) או מזהה משתמש (למשל user_009)." 
    else:
        yield "To check prescriptions, provide a prescription ID (e.g., RX-10001) or a user ID (e.g., user_009)."

 #simple - can be replaced by the LLM - based render_text_stream
def render_ask_rx_id_stream(lang: str) -> Iterator[str]:
    if lang == "he":
        yield "מה מספר המרשם? (למשל RX-10001)"
    else:
        yield "What is the prescription ID? (e.g., RX-10001)"

 #simple - can be replaced by the LLM - based render_text_stream
def render_ask_user_id_stream(lang: str) -> Iterator[str]:
    if lang == "he":
        yield "מה מזהה המשתמש שלך? (למשל user_009)"
    else:
        yield "What is your user ID? (e.g., user_009)"

 #simple - can be replaced by the LLM - based render_text_stream
def render_rx_not_found_stream(lang: str) -> Iterator[str]:
    if lang == "he":
        yield "לא מצאתי מרשם כזה במערכת. בדוק\י את תקינות המספר שהזנת (למשל RX-10001)."
    else:
        yield "I couldn’t find that prescription in the system. Please recheck the inserted ID (e.g., RX-10001)."

def render_user_not_found_stream(lang: str) -> Iterator[str]:
    if lang == "he":
        yield "לא מצאתי משתמש כזה במערכת. נסה\י מזהה כמו user_009."
    else:
        yield "I couldn’t find that user in םour system. Try an ID like user_009."

def render_user_rx_empty_stream(lang: str) -> Iterator[str]:
    if lang == "he":
        yield "לא נמצאו מרשמים למשתמש הזה במערכת."
    else:
        yield "No prescriptions were found for that user in the system."

# LLM verbalizer for factual rendering (recommended for bilingual polish).
def render_rx_verify_stream(lang: str, rx: dict) -> Iterator[str]:
    # rx: {rx_id,user_id,user_name,med_name,rx_status,expires_on}    
    instructions = (
        "You are a pharmacist assistant. Provide factual prescription related info only.\n"
        "No advice, no recommendations, no dosage, no diagnosis.\n"
        "DO NOT offer additional info besides the factual info you provide\n"
        "Keep it short.\n")
    facts = (
        f"Prescription {rx.get('rx_id')} — Status: {rx.get('rx_status')}.\n"
            f"Medication: {rx.get('med_name')}.\n"
            f"Expires on: {rx.get('expires_on')}.\n")
    return render_text_stream(lang, instructions, facts)  

def render_user_rx_list_stream(lang: str, user: dict, items: list[dict]) -> Iterator[str]:
    # user: {user_id,user_name} ; items: [{rx_id, med_name, rx_status, expires_on}]
    if not items:
        yield from render_user_rx_empty_stream(lang)
        return

    if lang == "he":
        lines = [f"מרשמים עבור {user.get('user_name')} ({user.get('user_id')}):"]
        for it in items:
            lines.append(f"- {it.get('rx_id')}: {it.get('med_name')} — {it.get('rx_status')} (עד {it.get('expires_on')})")
        lines.append("\nלהכוונה רפואית פנו לרופא/רוקח.")
        yield "\n".join(lines)
    else:
        lines = [f"Prescriptions for {user.get('user_name')} ({user.get('user_id')}):"]
        for it in items:
            lines.append(f"- {it.get('rx_id')}: {it.get('med_name')} — {it.get('rx_status')} (expires {it.get('expires_on')})")
        lines.append("\nfor medical guidance, consult a licensed doctor/pharmacist.")
        yield "\n".join(lines)