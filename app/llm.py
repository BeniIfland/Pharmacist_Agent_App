import os
from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def qury_llm(message: str) -> str:  #not good for streaming
    response = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "user", "content": message}])
    return response.choices[0].message.content


def stream_llm(message: str):

    with client.responses.stream(model="gpt-5",input=message,
            reasoning={"effort": "minimal"},      
                                 ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta #generator to enable streaming | its good to avoid async for etc....


# class MedicineExtraction(BaseModel):
#     medicine: Optional[str]


def extract_med_name(text: str) -> str | None:
    """
    Extract medicine name out of user provided text    
    :param text: Description
    :type text: str
    :return: Description
    :rtype: str | None
    """
    #TODO: add a small sanitization and a guardrail agains PI- for security vertical
    #TODO: can add a simple string manipulation on 'text' as part of sanitization
    #TODO: deal with ambiguity or several medicines in user's message
    #TODO: refine prompt (from paper + chat)
    resp = client.responses.create(
        model="gpt-5",
        input=[
            {
                "role": "system",
                "content": (
                    "You are a professional entity extractor specializing in medicine names.\n"
                    "Your task:\n"
                    "1. Read the user's text carefully.\n"
                    "2. Identify the name of the medicine mentioned.\n"
                    "3. Return ONLY the medicine name.\n"
                    "4. If no medicine is identified, return null.\n"
                    "\n"
                    "Examples:\n"
                    "Input: tell me about aspirin\n"
                    "Output: aspirin\n"
                    "\n"
                    "Input: tell me about Hindu history\n"
                    "Output: null\n"
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

