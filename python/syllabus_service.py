import json
import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GOOGLE_CREDENTIALS = Path(__file__).resolve().parents[1] / "google-api-key.json"
DEFAULT_INPUT_PATH = Path(__file__).with_name("inputs") / "space.json"
PROMPT_PATH = Path(__file__).with_name("syllabus_prompt.txt")
SKILL_PATH = BASE_DIR / "skills" / "content_generator" / "SKILL.md"
SUB_CONTENT_SKILL_PATH = BASE_DIR / "skills" / "sub_content_generator" / "SKILL.md"
DEFAULT_CONTENT_CACHE_DIR = BASE_DIR / ".cache" / "content_generation"
CONTENT_GENERATION_SKILL_NAME = "content_generation"

if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from pipeline.cache_manager import get_cached_output, make_cache_key, save_cached_output
from pipeline.skill_registry import get_skill

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


def load_sub_content_generation_skill(skill_path=SUB_CONTENT_SKILL_PATH):
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")
    return skill_path.read_text(encoding="utf-8")


def build_syllabus_prompt(payload, prompt_path=PROMPT_PATH):
    syllabus_prompt = load_system_prompt(prompt_path)
    user_input = json.dumps(payload, indent=2, ensure_ascii=False)

    return (
        f"{syllabus_prompt}\n\n"
        f"User input:\n{user_input}\n\n"
        "Generate JSON that follows the syllabus instructions only. Return JSON only."
    )


def build_content_prompt(payload, syllabus, skill_path=SKILL_PATH):
    skill_instruction = load_content_generation_skill(skill_path)
    content_input = {
        "request": payload,
        "syllabus_context": {
            "topic": syllabus.get("topic"),
            "pedagogical_style": syllabus.get("pedagogical_style"),
            "goals": syllabus.get("goals", []),
            "syllabus": syllabus.get("syllabus", []),
        },
    }

    return (
        f"{skill_instruction}\n\n"
        f"Input:\n{json.dumps(content_input, indent=2, ensure_ascii=False)}\n\n"
        "Generate only the content object that follows the content_generator SKILL.md instructions. "
        "Align the topics and assessments with the provided syllabus_context. Return JSON only."
    )


def build_sub_content_prompt(topic, course_context, skill_path=SUB_CONTENT_SKILL_PATH):
    skill_instruction = load_sub_content_generation_skill(skill_path)

    sub_content_input = {
        "course_context": course_context,
        "topic": topic,
    }

    return (
        f"{skill_instruction}\n\n"
        f"Input:\n{json.dumps(sub_content_input, indent=2, ensure_ascii=False)}\n\n"
        "Generate JSON that follows the sub_content_generator SKILL.md instructions. "
        "Return JSON only."
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

    decoder = json.JSONDecoder()

    try:
        return decoder.raw_decode(text)[0]
    except json.JSONDecodeError:
        pass

    for index, char in enumerate(text):
        if char not in "[{":
            continue

        try:
            return decoder.raw_decode(text[index:])[0]
        except json.JSONDecodeError:
            continue

    raise json.JSONDecodeError("No valid JSON object found in model response", text, 0)


def build_content_cache_input(topic, course_context):
    return {
        "course_title": course_context.get("topic"),
        "topic_title": topic.get("topic_title"),
        "topic_description": topic.get("topic_description"),
        "topic_learning_objectives": topic.get("learning_objectives"),
        "difficulty_level": course_context.get("difficulty_level"),
        "estimated_duration": topic.get("estimated_hours"),
        "learning_style": course_context.get("learning_style"),
        "hours_per_week": course_context.get("hours_per_week"),
        "personal_parameters": course_context.get("personal_parameters", []),
        "goals": course_context.get("goals", []),
        "assessments": topic.get("assessments", []),
        "output_format": {
            "topic_title": "string",
            "sub_contents": [
                {
                    "content_title": "string",
                    "content_text": "string",
                }
            ],
        },
    }


def validate_content_output(output):
    if not isinstance(output, dict):
        raise ValueError("Content output must be a JSON object.")

    topic_title = output.get("topic_title")
    if not isinstance(topic_title, str) or not topic_title.strip():
        raise ValueError("Content output is missing topic_title.")

    sub_contents = output.get("sub_contents")
    if not isinstance(sub_contents, list) or not sub_contents:
        raise ValueError("Content output must include non-empty sub_contents.")

    for index, chunk in enumerate(sub_contents, start=1):
        if not isinstance(chunk, dict):
            raise ValueError(f"Content chunk {index} must be a JSON object.")

        content_title = chunk.get("content_title") or chunk.get("title")
        content_text = chunk.get("content_text") or chunk.get("content") or chunk.get("text")

        if not isinstance(content_title, str) or not content_title.strip():
            raise ValueError(f"Content chunk {index} is missing content_title.")

        if not isinstance(content_text, str) or not content_text.strip():
            raise ValueError(f"Content chunk {index} is missing content text.")


def call_sub_content_generation_llm(topic, course_context, client, model_name, skill_path):
    response = client.models.generate_content(
        model=model_name,
        contents=build_sub_content_prompt(topic, course_context, skill_path=skill_path),
        config={
            "system_instruction": "You generate valid JSON instructional sub-content chunks only.",
            "temperature": 0.3,
        },
    )

    return parse_model_response(response.text)


def merge_generated_sections(payload, syllabus, content):
    return {
        "topic": syllabus.get("topic", payload.get("target_skill")),
        "duration_weeks": payload.get("duration_weeks"),
        "difficulty_level": payload.get("difficulty_level"),
        "learning_style": payload.get("learning_style"),
        "hours_per_week": payload.get("hours_per_week"),
        "personal_parameters": payload.get("personal_parameters", []),
        "pedagogical_style": syllabus.get("pedagogical_style"),
        "goals": syllabus.get("goals", []),
        "syllabus": syllabus.get("syllabus", []),
        "content": content,
    }


def generate_syllabus_outline(payload, client=None, model_name="gemini-2.5-flash"):
    if client is None:
        client = build_client()

    response = client.models.generate_content(
        model=model_name,
        contents=build_syllabus_prompt(payload),
        config={
            "system_instruction": "You generate valid JSON syllabus plans only.",
            "temperature": 0.3,
        },
    )

    return parse_model_response(response.text)


def generate_content_plan(payload, syllabus, client=None, model_name="gemini-2.5-flash"):
    if client is None:
        client = build_client()

    response = client.models.generate_content(
        model=model_name,
        contents=build_content_prompt(payload, syllabus),
        config={
            "system_instruction": "You generate valid JSON content plans only.",
            "temperature": 0.3,
        },
    )

    return parse_model_response(response.text)


def generate_sub_contents_for_topic(
    topic,
    course_context,
    client=None,
    model_name="gemini-2.5-flash",
    cache_dir=None,
):
    if client is None:
        client = build_client()

    if cache_dir is None:
        cache_dir = DEFAULT_CONTENT_CACHE_DIR

    skill = get_skill(CONTENT_GENERATION_SKILL_NAME)
    topic_label = topic.get("topic_title", "<unknown topic>")

    cache_input = build_content_cache_input(topic, course_context)
    cache_key = make_cache_key(
        skill_name=skill["name"],
        skill_version=skill["version"],
        input_data=cache_input,
    )

    if skill.get("cacheable", False):
        cached_output = get_cached_output(cache_key, cache_dir=cache_dir)
        if cached_output is not None:
            try:
                validate_content_output(cached_output)
                print(f"[cache hit] {skill['name']}: {topic_label}")
                return cached_output
            except ValueError:
                print(f"[cache invalid] {skill['name']}: {topic_label}, regenerating...")

    print(f"[cache miss] {skill['name']}: {topic_label}, calling LLM...")
    output = call_sub_content_generation_llm(
        topic=topic,
        course_context=course_context,
        client=client,
        model_name=model_name,
        skill_path=skill["skill_path"],
    )
    validate_content_output(output)

    if skill.get("cacheable", False):
        save_cached_output(cache_key, output, cache_dir=cache_dir)
        print(f"[cache saved] {skill['name']}: {topic_label}")

    return output


def add_sub_contents(output, client=None, model_name="gemini-2.5-flash", cache_dir=None):
    if client is None:
        client = build_client()

    course_context = {
        "topic": output.get("topic"),
        "duration_weeks": output.get("duration_weeks"),
        "difficulty_level": output.get("difficulty_level"),
        "learning_style": output.get("learning_style"),
        "hours_per_week": output.get("hours_per_week"),
        "personal_parameters": output.get("personal_parameters", []),
        "goals": output.get("goals", []),
    }

    topics = output.get("content", {}).get("topics", [])

    for topic in topics:
        sub_content_result = generate_sub_contents_for_topic(
            topic=topic,
            course_context=course_context,
            client=client,
            model_name=model_name,
            cache_dir=cache_dir,
        )
        topic["sub_contents"] = sub_content_result.get("sub_contents", [])

    return output


def generate_syllabus(payload, client=None, model_name="gemini-2.5-flash", cache_dir=None):
    if client is None:
        client = build_client()

    syllabus = generate_syllabus_outline(payload, client=client, model_name=model_name)
    content = generate_content_plan(payload, syllabus, client=client, model_name=model_name)
    output = merge_generated_sections(payload, syllabus, content)
    return add_sub_contents(output, client=client, model_name=model_name, cache_dir=cache_dir)
