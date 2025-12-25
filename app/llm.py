import os
from openai import OpenAI
from dotenv import load_dotenv
import time

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