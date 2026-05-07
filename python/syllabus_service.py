import json
import os
from pathlib import Path


DEFAULT_GOOGLE_CREDENTIALS = Path(__file__).resolve().parents[1] / "google-api-key.json"
DEFAULT_INPUT_PATH = Path(__file__).with_name("inputs") / "space.json"
PROMPT_PATH = Path(__file__).with_name("syllabus_prompt.txt")

if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and DEFAULT_GOOGLE_CREDENTIALS.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(DEFAULT_GOOGLE_CREDENTIALS)


def load_payload(input_path):
    with open(input_path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_system_prompt(prompt_path=PROMPT_PATH):
    with open(prompt_path, "r", encoding="utf-8") as file:
        return file.read()


def build_client():
    from google import genai

    return genai.Client(
        vertexai=True,
        project="mcc-ece-gemini",
        location="us-central1",
    )


def parse_model_response(text):
    text = text.strip()

    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    return json.loads(text)


def generate_syllabus(payload, client=None, model_name="gemini-2.5-flash"):
    if client is None:
        client = build_client()

    response = client.models.generate_content(
        model=model_name,
        contents=json.dumps(payload),
        config={
            "system_instruction": load_system_prompt(),
            "temperature": 0.3,
        },
    )

    return parse_model_response(response.text)
