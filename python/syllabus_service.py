import json
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GOOGLE_CREDENTIALS = Path(__file__).resolve().parents[1] / "google-api-key.json"
DEFAULT_INPUT_PATH = Path(__file__).with_name("inputs") / "space.json"
PROMPT_PATH = Path(__file__).with_name("syllabus_prompt.txt")
SKILL_PATH = BASE_DIR / "skills" / "content_generator" / "SKILL.md"

if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and DEFAULT_GOOGLE_CREDENTIALS.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(DEFAULT_GOOGLE_CREDENTIALS)


def load_payload(input_path):
    with open(input_path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_system_prompt(prompt_path=PROMPT_PATH):
    with open(prompt_path, "r", encoding="utf-8") as file:
        return file.read()


def load_content_generation_skill(skill_path=SKILL_PATH):
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")
    return skill_path.read_text(encoding="utf-8")


def build_generation_prompt(payload, prompt_path=PROMPT_PATH, skill_path=SKILL_PATH):
    skill_instruction = load_content_generation_skill(skill_path)
    syllabus_prompt = load_system_prompt(prompt_path)
    user_input = json.dumps(payload, indent=2, ensure_ascii=False)

    return (
        f"{skill_instruction}\n\n"
        f"Existing syllabus prompt:\n{syllabus_prompt}\n\n"
        f"User input:\n{user_input}\n\n"
        "Generate one JSON response that includes the syllabus top-level structure and a nested content object "
        "that follows the SKILL.md instructions. Return JSON only."
    )


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
        contents=build_generation_prompt(payload),
        config={
            "system_instruction": load_system_prompt(),
            "temperature": 0.3,
        },
    )

    return parse_model_response(response.text)
