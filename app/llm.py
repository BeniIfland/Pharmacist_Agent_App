import os
from openai import OpenAI
from dotenv import load_dotenv
# from pydantic import BaseModel
# from typing import Optional
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
        model="gpt-5-mini",
        reasoning={"effort": "minimal"},
        max_output_tokens=120,
        input=(
            "You are an intent router for a Pharmacist Assistant.\n"
            "Your goal is to return a JSON which classifies user's intent."
            "Return ONLY a valid JSON and nothing else.\n\n"
            "Allowed intents:\n"
            "- med_info: user asks about a medication name or information AVOID confusing when he asks for a medical advice or guidance unrelated to specific medicines.\n"
            "- stock_check: user asks if a medication is available or in stock in a branch/city/store.\n"
            "- small_talk: greetings, thanks, 'what can you do', casual chit-chat, any message that is not related to specific medicines, including sales, encouragments or a behavior that is unsafe for the customer or that out of the scope of a Pharmacist Assistant chatbot or that is not covered by the aforementioned intents.\n"
            "Language:\n"
            "- lang must be 'he' if the user wrote in Hebrew letters, else 'en'.\n\n"
            "JSON schema:\n"
            "{\n"
            '  "intent": "med_info|small_talk",\n'
            '  "confidence": <a float [0,1] that express your confidence in the decision>,\n' #debugging,evaluation,future fuardrail
            '  "lang": "he|en",\n'
            '  "notes": <a short description on why you chose this intent>\n' #debugging and evaluation
            "}\n\n"
            f"User message:\n{text}"
        ),
    )
    print("[router raw]", resp.output_text) #TODO: delete itstemporary for debugging
    raw = resp.output_text or ""
    json_str = _extract_json_object(raw)
    data = json.loads(json_str)

    # Validate using Pydantic
    return IntentResult.model_validate(data)

#TODO: remove if not used
def qury_llm(message: str) -> str:  #not good for streaming
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "user", "content": message}])
    return response.choices[0].message.content


#TODO: remove if not used
def stream_llm(message: str):

    with client.responses.stream(model="gpt-5-mini",input=message, #most LLM responses are cotrolled and broken down by the flow - hence a small version is better and faster
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
    #TODO: add a small sanitization and a guardrail agains PI- for security vertical
    #TODO: can add a simple string manipulation on 'text' as part of sanitization
    #TODO: deal with ambiguity or several medicines in user's message
    #TODO: refine prompt (from paper + chat)
    resp = client.responses.create(
        model="gpt-5-mini",
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

# def render_med_info(lang: str, med: dict) -> str: #for translation
#     prompt = f"""
# You are a pharmacist assistant UI text generator.
# Rules:
# - Reply in {'Hebrew' if lang=='he' else 'English'}.
# - Use ONLY the facts provided. DO NOT add dosage, advice, diagnosis, or recommendations.
# - DO NOT encourage purchasing.
# - Keep your answers brief and concise.

# Facts:
# Name: {med['display_name']}
# Active ingredient: {med['active_ingredient']}
# Prescription required: {med['rx_required']}
# Summary: {med['label_summary']}
# """
#     resp = client.responses.create(
#         model="gpt-5-mini",
#         input=prompt,
#         reasoning={"effort": "minimal"},
#         # max_output_tokens=120,
#     )
#     return resp.output_text.strip()

from typing import Iterator
from openai import OpenAI

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
- You are allowed to respond ONLY in English or Hebrew
- This time reply in {language}.
- Use ONLY the facts provided provided to generate your response. Do not add medical advice, diagnosis, dosage, recommendations, or purchase encouragement from your prior knowledge.
- If the user asks for advice, refuse briefly and suggest consulting a pharmacist/doctor (in the same language).
- Keep it concise (3-6 short lines).
- If you are missing a required fact, ask a short clarifying question.
- You HAVE to follow the following instruction:

Instruction:
{instruction}

Facts:
{facts}
""".strip()

    with client.responses.stream(
        model="gpt-5-mini",
        input=prompt,
        reasoning={"effort": "minimal"},
        max_output_tokens=160, #limiting the model for UX and avoid hallucinations and be token efficient
        ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta


def render_med_info_stream(lang: str, med: dict) -> Iterator[str]:
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
    facts = f"""Name: {med["display_name"]}
        Active ingredient: {med["active_ingredient"]}
        Prescription required: {med["rx_required"]}
        Summary: {med["label_summary"]}"""
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
    instruction = "Inform the user the medication was not found in the database and ask for a different name or spelling."
    facts = "Result: NOT_FOUND"
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
        "You may greet, thank, and explain your capabilities. "
        "Do NOT provide medical advice, diagnosis, or recommendations."
    )
    facts = (
        f"User said: {user_text}\n"
        "Capabilities: factual medication info, availability, prescription requirement.\n"
        "If user asks for personal guidance: suggest consulting a pharmacist/doctor."
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