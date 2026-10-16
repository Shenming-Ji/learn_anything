import json
import os
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

try:
    from google import genai
except ModuleNotFoundError:  # pragma: no cover - handled at runtime when client creation is needed
    genai = None


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GOOGLE_CREDENTIALS = Path(__file__).resolve().parents[1] / "google-api-key.json"
DEFAULT_INPUT_PATH = Path(__file__).with_name("inputs") / "space.json"
DEFAULT_CONTENT_TEST_INPUT_PATH = Path(__file__).with_name("inputs") / "linear_regression_content_test.json"
PROMPT_PATH = Path(__file__).with_name("syllabus_prompt.txt")
CONTENT_TEST_PROMPT_PATH = Path(__file__).with_name("content_test_prompt.txt")
SKILL_PATH = BASE_DIR / "skills" / "content_generator" / "SKILL.md"
SUB_CONTENT_SKILL_PATH = BASE_DIR / "skills" / "sub_content_generator" / "SKILL.md"
CONTENT_TEST_OUTPUT_DIR = BASE_DIR / "content_test_outputs"
CONTENT_GENERATION_SKILL_NAME = "content_generation"
MIN_SUB_CONTENTS_PER_TOPIC = 4
TEMPERATURE = 0.1
MAX_TOKENS = 8192

if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from pipeline.skill_registry import get_skill

if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and DEFAULT_GOOGLE_CREDENTIALS.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(DEFAULT_GOOGLE_CREDENTIALS)


class ContentTestStageError(Exception):
    def __init__(self, stage_name, raw_model_output, error, input_payload):
        super().__init__(str(error))
        self.stage_name = stage_name
        self.raw_model_output = raw_model_output
        self.input_payload = input_payload
        self.original_error = error


def load_payload(input_path):
    with open(input_path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_system_prompt(prompt_path=PROMPT_PATH):
    with open(prompt_path, "r", encoding="utf-8") as file:
        return file.read()


def load_content_test_prompt(prompt_path=CONTENT_TEST_PROMPT_PATH):
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


def build_syllabus_prompt(payload, outline_feedback="", regenerate=False, prompt_path=PROMPT_PATH):
    syllabus_prompt = load_system_prompt(prompt_path)
    user_input = json.dumps(payload, indent=2, ensure_ascii=False)
    feedback = str(outline_feedback or "").strip()
    guidance = ""

    if feedback:
        guidance = (
            "\n\nAdditional syllabus guidance for this generation:\n"
            f"{feedback}\n\n"
            "Treat this guidance as higher priority than stylistic defaults when you regenerate the outline."
        )
    elif regenerate:
        guidance = (
            "\n\nThis is a regeneration request with no extra user guidance.\n"
            "Produce a meaningfully different but still valid outline variation from a typical first draft."
        )

    return (
        f"{syllabus_prompt}\n\n"
        f"User input:\n{user_input}\n\n"
        f"{guidance}\n"
        "Generate JSON that follows the syllabus instructions only. Return JSON only."
    )


def build_content_prompt(payload, syllabus, skill_path=SKILL_PATH):
    skill_instruction = load_content_generation_skill(skill_path)
    content_input = build_content_generation_input(payload, syllabus)

    return (
        f"{skill_instruction}\n\n"
        f"Input:\n{json.dumps(content_input, indent=2, ensure_ascii=False)}\n\n"
        "Generate only the content object that follows the content_generator SKILL.md instructions. "
        "Align the topics and assessments with the provided syllabus_context. "
        "Each topic_description should preview the most useful instructional elements for that topic, "
        "such as formulas, worked examples, graph interpretation, tables, code examples, media guidance, "
        "or source recommendations, but do not add any new schema fields. Return JSON only."
    )


def build_content_generation_input(payload, syllabus):
    return {
        "request": payload,
        "syllabus_context": {
            "topic": syllabus.get("topic"),
            "pedagogical_style": syllabus.get("pedagogical_style"),
            "goals": syllabus.get("goals", []),
            "syllabus": syllabus.get("syllabus", []),
        },
    }


def build_content_test_prompt(payload, syllabus, prompt_path=CONTENT_TEST_PROMPT_PATH):
    prompt = load_content_test_prompt(prompt_path)
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
        f"{prompt}\n\n"
        f"Input:\n{json.dumps(content_input, indent=2, ensure_ascii=False)}\n\n"
        "Analyze the syllabus/topic to determine which content types are necessary, then return "
        "the final structured JSON only. No markdown. No prose outside JSON."
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
        "The top-level object must include `topic_title` and a non-empty `sub_contents` array. "
        f"Generate at least {MIN_SUB_CONTENTS_PER_TOPIC} distinct `sub_contents` items. Do not collapse the topic into a single lesson. "
        "Each item in `sub_contents` must include `content_title` and `content_text`. "
        "For each content, decide whether formulas, worked examples, graph descriptions, tables, code examples, "
        "media or image guidance, or source recommendations are needed, and include them naturally inside `content_text` only when helpful. "
        "Keep the content specific to the topic and avoid repeating the same generic introduction across lessons. "
        "Because the output must be valid JSON, escape backslashes correctly inside JSON strings when writing LaTeX or similar notation. "
        "Return JSON only."
    )


def build_client():
    if genai is None:
        raise ModuleNotFoundError(
            "google.genai is required to generate content. Install the Google GenAI SDK to run this pipeline."
        )
    return genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
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

    repaired_text = _escape_invalid_json_backslashes(text)
    if repaired_text != text:
        try:
            return decoder.raw_decode(repaired_text)[0]
        except json.JSONDecodeError:
            pass

    for index, char in enumerate(text):
        if char not in "[{":
            continue

        try:
            return decoder.raw_decode(text[index:])[0]
        except json.JSONDecodeError:
            continue

        repaired_slice = _escape_invalid_json_backslashes(text[index:])
        if repaired_slice != text[index:]:
            try:
                return decoder.raw_decode(repaired_slice)[0]
            except json.JSONDecodeError:
                continue

    raise json.JSONDecodeError("No valid JSON object found in model response", text, 0)


def _escape_invalid_json_backslashes(text):
    valid_escapes = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}
    result = []
    in_string = False
    index = 0

    while index < len(text):
        char = text[index]

        if not in_string:
            result.append(char)
            if char == '"':
                in_string = True
            index += 1
            continue

        if char == '"':
            result.append(char)
            in_string = False
            index += 1
            continue

        if char != "\\":
            result.append(char)
            index += 1
            continue

        next_index = index + 1
        if next_index >= len(text):
            result.append("\\\\")
            index += 1
            continue

        next_char = text[next_index]
        if next_char in valid_escapes:
            result.append(char)
            result.append(next_char)
        else:
            result.append("\\\\")
            result.append(next_char)
        index += 2

    return "".join(result)


def _coerce_string_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_object_list(value):
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _coerce_needed_flag(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "needed", "required"}:
            return True
        if lowered in {"false", "no", "not needed", "optional"}:
            return False
    return bool(value)


def _normalize_needed_block(value):
    if isinstance(value, list):
        return {
            "needed": bool(value),
            "reason": "",
            "items": [item for item in value if isinstance(item, dict)],
        }

    if not isinstance(value, dict):
        return {"needed": False, "reason": "", "items": []}

    normalized = dict(value)
    items = normalized.get("items")
    if not isinstance(items, list):
        items = []

    normalized["needed"] = _coerce_needed_flag(normalized.get("needed"))
    normalized["reason"] = str(normalized.get("reason", "") or "").strip()
    normalized["items"] = [item for item in items if isinstance(item, dict)]
    return normalized


def normalize_content_test_output(output, payload=None, syllabus=None):
    if not isinstance(output, dict):
        return output

    normalized = dict(output)
    fallback_topic = ""
    if isinstance(syllabus, dict):
        fallback_topic = str(syllabus.get("topic", "") or "").strip()
    if not fallback_topic and isinstance(payload, dict):
        fallback_topic = str(payload.get("target_skill", "") or "").strip()

    topic = str(normalized.get("topic", "") or "").strip() or fallback_topic
    normalized["topic"] = topic
    normalized["learning_objectives"] = _coerce_string_list(normalized.get("learning_objectives"))
    normalized["key_concepts"] = _coerce_string_list(normalized.get("key_concepts"))
    normalized["formulas"] = _normalize_needed_block(normalized.get("formulas"))
    normalized["examples"] = _coerce_object_list(normalized.get("examples"))
    normalized["graphs_or_visuals_needed"] = _normalize_needed_block(normalized.get("graphs_or_visuals_needed"))
    normalized["tables_needed"] = _normalize_needed_block(normalized.get("tables_needed"))
    normalized["code_examples_needed"] = _normalize_needed_block(normalized.get("code_examples_needed"))
    normalized["media_or_images_needed"] = _normalize_needed_block(normalized.get("media_or_images_needed"))
    normalized["citations_needed"] = _normalize_needed_block(normalized.get("citations_needed"))
    normalized["generated_sections"] = _coerce_object_list(normalized.get("generated_sections"))
    normalized["quizzes_or_checkpoints"] = _coerce_object_list(normalized.get("quizzes_or_checkpoints"))
    normalized["assumptions_or_missing_info"] = _coerce_string_list(normalized.get("assumptions_or_missing_info"))
    return normalized


def validate_generated_content_plan(output, require_sub_contents=False):
    if not isinstance(output, dict):
        raise ValueError("Generated content plan must be a JSON object.")

    for field_name in ("skill_name", "description", "difficulty_level", "target_audience"):
        value = output.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Generated content plan is missing {field_name}.")

    topics = output.get("topics")
    if not isinstance(topics, list) or not topics:
        raise ValueError("Generated content plan must include a non-empty topics list.")

    for index, topic in enumerate(topics, start=1):
        if not isinstance(topic, dict):
            raise ValueError(f"Topic {index} must be a JSON object.")

        topic_title = topic.get("topic_title")
        topic_description = topic.get("topic_description")
        estimated_hours = topic.get("estimated_hours")
        assessment_count = topic.get("assessment_count")
        assessments = topic.get("assessments")

        if not isinstance(topic_title, str) or not topic_title.strip():
            raise ValueError(f"Topic {index} is missing topic_title.")
        if not isinstance(topic_description, str) or not topic_description.strip():
            raise ValueError(f"Topic {index} is missing topic_description.")
        if not isinstance(estimated_hours, (int, float)) or estimated_hours <= 0:
            raise ValueError(f"Topic {index} must include a positive estimated_hours value.")
        if not isinstance(assessments, list) or not assessments:
            raise ValueError(f"Topic {index} must include a non-empty assessments list.")
        if not isinstance(assessment_count, int):
            raise ValueError(f"Topic {index} is missing assessment_count.")
        if assessment_count != len(assessments):
            raise ValueError(f"Topic {index} assessment_count does not match assessments length.")
        if require_sub_contents:
            validate_content_output(
                {
                    "topic_title": topic_title,
                    "sub_contents": topic.get("sub_contents"),
                }
            )
        elif "sub_contents" in topic:
            raise ValueError("Content generator output must not include sub_contents.")


def validate_content_test_output(output):
    if not isinstance(output, dict):
        raise ValueError("Content test output must be a JSON object.")

    content = output.get("content")
    if not isinstance(content, dict):
        raise ValueError("Content test output must include a content object.")

    validate_generated_content_plan(content, require_sub_contents=True)


def summarize_content_test_output(output):
    content = output.get("content", {}) if isinstance(output, dict) else {}
    topics = content.get("topics", []) if isinstance(content, dict) else []

    topic_count = len(topics) if isinstance(topics, list) else 0
    total_sub_contents = 0
    every_sub_content_has_page_assessment = True
    min_word_count = None
    assessment_count_matches = True

    if isinstance(topics, list):
        for topic in topics:
            if not isinstance(topic, dict):
                every_sub_content_has_page_assessment = False
                assessment_count_matches = False
                continue

            assessments = topic.get("assessments")
            declared_count = topic.get("assessment_count")
            if not isinstance(assessments, list) or not isinstance(declared_count, int) or declared_count != len(assessments):
                assessment_count_matches = False

            sub_contents = topic.get("sub_contents")
            if not isinstance(sub_contents, list):
                every_sub_content_has_page_assessment = False
                continue

            total_sub_contents += len(sub_contents)
            for sub_content in sub_contents:
                if not isinstance(sub_content, dict):
                    every_sub_content_has_page_assessment = False
                    continue

                if not isinstance(sub_content.get("page_assessment"), dict):
                    every_sub_content_has_page_assessment = False

                word_count = len(str(sub_content.get("content_text", "") or "").split())
                if min_word_count is None or word_count < min_word_count:
                    min_word_count = word_count

    if min_word_count is None:
        min_word_count = 0

    return {
        "topic_count": topic_count,
        "total_sub_contents": total_sub_contents,
        "every_sub_content_has_page_assessment": every_sub_content_has_page_assessment,
        "minimum_content_text_word_count": min_word_count,
        "assessment_count_matches": assessment_count_matches,
    }


def _slugify_filename_part(value):
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return cleaned or "content_test"


def _content_test_timestamp():
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def _ensure_output_dir(output_dir=CONTENT_TEST_OUTPUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _build_content_test_file_path(topic_slug, suffix="", output_dir=CONTENT_TEST_OUTPUT_DIR):
    output_dir = _ensure_output_dir(output_dir)
    timestamp = _content_test_timestamp()
    base_name = f"{topic_slug}_{timestamp}{suffix}"
    path = output_dir / f"{base_name}.json"
    counter = 2

    while path.exists():
        path = output_dir / f"{base_name}_{counter}.json"
        counter += 1

    return path


def _content_test_slug_source(output=None, payload=None, input_payload=None):
    candidates = []

    if isinstance(input_payload, dict):
        candidates.extend(
            [
                input_payload.get("topic_title"),
                input_payload.get("topic"),
                input_payload.get("target_skill"),
            ]
        )
        request = input_payload.get("request")
        if isinstance(request, dict):
            candidates.append(request.get("target_skill"))
        course_context = input_payload.get("course_context")
        if isinstance(course_context, dict):
            candidates.append(course_context.get("topic"))

    if isinstance(payload, dict):
        candidates.append(payload.get("target_skill"))

    if isinstance(output, dict):
        candidates.append(output.get("topic"))
        content = output.get("content")
        if isinstance(content, dict):
            topics = content.get("topics")
            if isinstance(topics, list) and topics:
                first_topic = topics[0]
                if isinstance(first_topic, dict):
                    candidates.append(strip_topic_index(first_topic.get("topic_title")))

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    return "content_test"


def save_content_test_output(output, payload=None, output_dir=CONTENT_TEST_OUTPUT_DIR):
    topic_slug = _slugify_filename_part(_content_test_slug_source(output=output, payload=payload))
    path = _build_content_test_file_path(topic_slug, output_dir=output_dir)
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_content_test_debug(
    stage_name,
    raw_model_output,
    error_message,
    input_payload,
    output_dir=CONTENT_TEST_OUTPUT_DIR,
):
    topic_slug = _slugify_filename_part(_content_test_slug_source(input_payload=input_payload))
    path = _build_content_test_file_path(topic_slug, suffix="_debug", output_dir=output_dir)
    debug_payload = {
        "stage_name": stage_name,
        "raw_model_output": raw_model_output,
        "error_message": str(error_message),
        "input_payload": input_payload,
        "timestamp": datetime.now().isoformat(),
    }
    path.write_text(json.dumps(debug_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def normalize_content_output(output, topic=None):
    if isinstance(output, list):
        output = {"sub_contents": output}
    elif not isinstance(output, dict):
        return output

    normalized_output = dict(output)

    topic_title = normalized_output.get("topic_title")
    if (not isinstance(topic_title, str) or not topic_title.strip()) and topic is not None:
        fallback_title = topic.get("topic_title")
        if isinstance(fallback_title, str) and fallback_title.strip():
            normalized_output["topic_title"] = fallback_title.strip()

    raw_sub_contents = normalized_output.get("sub_contents")
    if not isinstance(raw_sub_contents, list) or not raw_sub_contents:
        for fallback_key in (
            "contents",
            "lessons",
            "sub_content",
            "subContent",
            "sections",
            "pages",
            "lesson_pages",
            "study_cards",
            "cards",
            "items",
            "chunks",
        ):
            fallback_value = normalized_output.get(fallback_key)
            if isinstance(fallback_value, list) and fallback_value:
                raw_sub_contents = fallback_value
                normalized_output["sub_contents"] = fallback_value
                break
            if isinstance(fallback_value, dict):
                nested_output = normalize_content_output(fallback_value, topic=topic)
                nested_sub_contents = (
                    nested_output.get("sub_contents")
                    if isinstance(nested_output, dict)
                    else None
                )
                if isinstance(nested_sub_contents, list) and nested_sub_contents:
                    raw_sub_contents = nested_sub_contents
                    normalized_output["sub_contents"] = nested_sub_contents
                    break

    if (not isinstance(raw_sub_contents, list) or not raw_sub_contents):
        standalone_title = (
            normalized_output.get("content_title")
            or normalized_output.get("title")
            or normalized_output.get("lesson_title")
            or normalized_output.get("section_title")
            or normalized_output.get("heading")
            or normalized_output.get("name")
        )
        standalone_text = (
            normalized_output.get("content_text")
            or normalized_output.get("content")
            or normalized_output.get("text")
            or normalized_output.get("body")
            or normalized_output.get("explanation")
            or normalized_output.get("lesson_text")
            or normalized_output.get("description")
        )
        if isinstance(standalone_title, str) and standalone_title.strip() and isinstance(standalone_text, str) and standalone_text.strip():
            raw_sub_contents = [{
                "content_title": standalone_title.strip(),
                "content_text": standalone_text.strip(),
            }]
            normalized_output["sub_contents"] = raw_sub_contents

    if isinstance(raw_sub_contents, list):
        normalized_sub_contents = []
        for index, chunk in enumerate(raw_sub_contents, start=1):
            if isinstance(chunk, str) and chunk.strip():
                normalized_sub_contents.append(
                    {
                        "content_title": f"Lesson {index}",
                        "content_text": chunk.strip(),
                    }
                )
                continue
            if not isinstance(chunk, dict):
                normalized_sub_contents.append(chunk)
                continue

            normalized_chunk = dict(chunk)
            if "content_title" not in normalized_chunk:
                for fallback_key in ("title", "lesson_title", "section_title", "heading", "name"):
                    fallback_value = normalized_chunk.get(fallback_key)
                    if isinstance(fallback_value, str) and fallback_value.strip():
                        normalized_chunk["content_title"] = fallback_value
                        break

            if "content_text" not in normalized_chunk:
                for fallback_key in ("content", "text", "body", "explanation", "lesson_text", "description"):
                    fallback_value = normalized_chunk.get(fallback_key)
                    if isinstance(fallback_value, str) and fallback_value.strip():
                        normalized_chunk["content_text"] = fallback_value
                        break

            normalized_sub_contents.append(normalized_chunk)

        normalized_output["sub_contents"] = normalized_sub_contents

    return normalized_output


def normalize_outline_output(output, payload=None):
    if isinstance(output, list):
        output = {"syllabus": output}
    elif not isinstance(output, dict):
        return output
    else:
        output = dict(output)

    normalized_output = dict(output)

    topic = normalized_output.get("topic")
    if (not isinstance(topic, str) or not topic.strip()) and isinstance(payload, dict):
        fallback_topic = payload.get("target_skill")
        if isinstance(fallback_topic, str) and fallback_topic.strip():
            normalized_output["topic"] = fallback_topic.strip()

    raw_syllabus = normalized_output.get("syllabus")
    if not isinstance(raw_syllabus, list):
        for fallback_key in ("weeks", "outline", "weekly_syllabus", "weekly_outline"):
            fallback_value = normalized_output.get(fallback_key)
            if isinstance(fallback_value, list):
                raw_syllabus = fallback_value
                normalized_output["syllabus"] = fallback_value
                break

    goals = normalized_output.get("goals")
    if goals is None:
        normalized_output["goals"] = []

    return normalized_output


def validate_content_output(output):
    if not isinstance(output, dict):
        raise ValueError("Content output must be a JSON object.")

    topic_title = output.get("topic_title")
    if not isinstance(topic_title, str) or not topic_title.strip():
        raise ValueError("Content output is missing topic_title.")

    sub_contents = output.get("sub_contents")
    if not isinstance(sub_contents, list) or not sub_contents:
        raise ValueError("Content output must include non-empty sub_contents.")
    if len(sub_contents) < MIN_SUB_CONTENTS_PER_TOPIC:
        raise ValueError(
            f"Content output must include at least {MIN_SUB_CONTENTS_PER_TOPIC} sub_contents."
        )

    for index, chunk in enumerate(sub_contents, start=1):
        if not isinstance(chunk, dict):
            raise ValueError(f"Content chunk {index} must be a JSON object.")

        content_title = chunk.get("content_title") or chunk.get("title")
        content_text = chunk.get("content_text") or chunk.get("content") or chunk.get("text")

        if not isinstance(content_title, str) or not content_title.strip():
            raise ValueError(f"Content chunk {index} is missing content_title.")

        if not isinstance(content_text, str) or not content_text.strip():
            raise ValueError(f"Content chunk {index} is missing content text.")


def validate_outline_output(output):
    if not isinstance(output, dict):
        raise ValueError("Outline output must be a JSON object.")

    topic = output.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("Outline output is missing topic.")

    syllabus = output.get("syllabus")
    if not isinstance(syllabus, list) or not syllabus:
        raise ValueError("Outline output must include a non-empty syllabus list.")


def _keyword_tokens(value):
    if not value:
        return set()
    return {token for token in re.findall(r"[a-z0-9]+", str(value).lower()) if len(token) > 2}


def _score_assessment_for_sub_content(assessment, sub_content):
    content_tokens = _keyword_tokens(sub_content.get("content_title", ""))
    content_tokens.update(_keyword_tokens(sub_content.get("content_text", "")))

    focus_tokens = set()
    for item in assessment.get("assessment_focus", []):
        focus_tokens.update(_keyword_tokens(item))

    description_tokens = _keyword_tokens(assessment.get("assessment_description", ""))
    title_tokens = _keyword_tokens(sub_content.get("content_title", ""))

    score = len(content_tokens & focus_tokens) * 3
    score += len(content_tokens & description_tokens)
    score += len(title_tokens & focus_tokens) * 2
    return score


def attach_page_assessments(topic):
    if not isinstance(topic, dict):
        return topic

    sub_contents = topic.get("sub_contents")
    raw_assessments = topic.get("assessments")
    if not isinstance(sub_contents, list) or not isinstance(raw_assessments, list) or not raw_assessments:
        return topic

    assessments = [assessment for assessment in raw_assessments if isinstance(assessment, dict)]
    if not assessments:
        return topic

    usage_counts = [0] * len(assessments)

    for chunk in sub_contents:
        if not isinstance(chunk, dict):
            continue
        if isinstance(chunk.get("page_assessment"), dict):
            continue

        unused_indexes = [index for index, count in enumerate(usage_counts) if count == 0]
        candidate_indexes = unused_indexes or list(range(len(assessments)))

        best_index = max(
            candidate_indexes,
            key=lambda idx: (
                _score_assessment_for_sub_content(assessments[idx], chunk),
                -usage_counts[idx],
                -idx,
            ),
        )
        chunk["page_assessment"] = deepcopy(assessments[best_index])
        usage_counts[best_index] += 1

    return topic


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


def strip_topic_index(text):
    return re.sub(r"^\d+(?:\.\d+)*\s+", "", str(text or "")).strip()


def build_fallback_sub_content_output(topic, course_context):
    topic_title = str(topic.get("topic_title") or "Untitled topic").strip()
    display_title = strip_topic_index(topic_title) or topic_title
    topic_description = str(topic.get("topic_description") or "").strip()
    learning_style = str(course_context.get("learning_style") or "practical").strip().lower()
    hours_per_week = course_context.get("hours_per_week")
    goals = [str(item).strip() for item in course_context.get("goals", []) if str(item).strip()]

    assessment_focus = []
    for assessment in topic.get("assessments", []):
        if not isinstance(assessment, dict):
            continue
        assessment_focus.extend(
            str(item).strip()
            for item in assessment.get("assessment_focus", [])
            if str(item).strip()
        )

    focus_text = ", ".join(dict.fromkeys(assessment_focus[:4]))
    goals_text = "; ".join(goals[:2]) if goals else "the main course goals"
    study_time_text = f" across roughly {hours_per_week} study hours per week" if hours_per_week else ""

    style_sentence = (
        "Use concrete examples, realistic applications, and step-by-step interpretation."
        if learning_style == "practical"
        else "Emphasize core definitions, conceptual structure, and the reasoning behind each idea."
    )
    intro_title = (
        display_title
        if re.search(r"\b(foundations?|fundamentals?)\b", display_title, flags=re.IGNORECASE)
        else f"{display_title} Foundations"
    )

    sub_contents = [
        {
            "content_title": intro_title,
            "content_text": (
                f"This lesson introduces the central idea behind {display_title} and why it matters in the course. "
                f"{topic_description or 'This section introduces the essential background, vocabulary, and scope learners need before moving deeper.'} "
                f"The goal is to help the learner build a clear mental model of the topic{study_time_text} so later examples feel connected rather than isolated. "
                f"This lesson should explain the basic terms, the problem this topic helps solve, and how it supports {goals_text}. "
                f"{style_sentence}"
            ),
        },
        {
            "content_title": f"How {display_title} Works",
            "content_text": (
                f"This lesson breaks {display_title} into its main components, relationships, and decision points. "
                f"It should explain the process in a structured way: what inputs matter, what choices are made, and what outputs or consequences follow. "
                f"Learners should come away understanding not only the surface description of the topic, but also the internal logic that makes it work in practice. "
                f"When useful, connect the explanation back to {topic_description or 'the main topic description'} so the instruction stays grounded and relevant."
            ),
        },
        {
            "content_title": f"Applying {display_title}",
            "content_text": (
                f"This lesson focuses on application. Show how {display_title} appears in a realistic learning or work scenario and walk through how someone would reason through it carefully. "
                f"The explanation should highlight tradeoffs, common judgment calls, and how a learner can tell whether they are applying the idea correctly. "
                f"{'Give especially concrete examples and practical interpretation steps. ' if learning_style == 'practical' else 'Keep the reasoning explicit and concept-first. '}"
                f"If assessments are targeting specific areas, connect the lesson to {focus_text or 'the most important concepts in the topic'}."
            ),
        },
        {
            "content_title": f"Common Pitfalls in {display_title}",
            "content_text": (
                f"This lesson closes the topic by surfacing mistakes, misconceptions, and weak reasoning patterns learners should avoid. "
                f"Explain what beginners often misunderstand, why those misunderstandings happen, and what checks they can use to self-correct. "
                f"Link the guidance back to {focus_text or 'the topic objectives'} so the learner can review with purpose. "
                f"The outcome should be that the learner feels ready to study the topic independently and answer related assessments with more confidence."
            ),
        },
    ]

    fallback_output = {
        "topic_title": topic_title,
        "sub_contents": sub_contents,
    }
    validate_content_output(fallback_output)
    return fallback_output


def merge_generated_sections(payload, syllabus, content):
    output = build_outline_preview(payload, syllabus)
    output["content"] = content
    return output


def build_outline_preview(payload, syllabus):
    syllabus = normalize_outline_output(syllabus, payload=payload)
    validate_outline_output(syllabus)
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
    }


def generate_syllabus_outline(
    payload,
    client=None,
    model_name="gemini-2.5-flash",
    outline_feedback="",
    regenerate=False,
):
    if client is None:
        client = build_client()

    response = client.models.generate_content(
        model=model_name,
        contents=build_syllabus_prompt(payload, outline_feedback=outline_feedback, regenerate=regenerate),
        config={
            "system_instruction": "You generate valid JSON syllabus plans only.",
            "temperature": 0.6 if regenerate else 0.3,
        },
    )

    output = parse_model_response(response.text)
    output = normalize_outline_output(output, payload=payload)
    validate_outline_output(output)
    return output


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


def _normalize_generated_content_plan(output):
    if isinstance(output, dict) and isinstance(output.get("content"), dict):
        return dict(output["content"])
    return output


def _generate_content_plan_for_content_test(
    payload,
    syllabus,
    client,
    model_name,
    max_attempts=2,
):
    content_input = build_content_generation_input(payload, syllabus)
    last_raw_output = ""
    last_error = None

    for _ in range(max_attempts):
        response = client.models.generate_content(
            model=model_name,
            contents=build_content_prompt(payload, syllabus),
            config={
                "system_instruction": "You generate valid JSON content plans only.",
                "temperature": 0.2,
                "response_mime_type": "application/json",
            },
        )
        last_raw_output = response.text or ""

        try:
            output = parse_model_response(last_raw_output)
            output = _normalize_generated_content_plan(output)
            validate_generated_content_plan(output, require_sub_contents=False)
            return output
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc

    raise ContentTestStageError(
        "content_generator",
        last_raw_output,
        last_error or "Unknown content_generator parsing error.",
        content_input,
    )


def _build_content_test_course_context(payload, syllabus):
    return {
        "topic": syllabus.get("topic", payload.get("target_skill")),
        "duration_weeks": payload.get("duration_weeks"),
        "difficulty_level": payload.get("difficulty_level"),
        "learning_style": payload.get("learning_style"),
        "hours_per_week": payload.get("hours_per_week"),
        "personal_parameters": payload.get("personal_parameters", []),
        "goals": syllabus.get("goals", []),
    }


def _generate_sub_contents_for_content_test_topic(
    topic,
    course_context,
    client,
    model_name,
    max_attempts=2,
):
    skill = get_skill(CONTENT_GENERATION_SKILL_NAME)
    sub_content_input = {
        "course_context": course_context,
        "topic": topic,
    }
    last_raw_output = ""
    last_error = None

    for _ in range(max_attempts):
        response = client.models.generate_content(
            model=model_name,
            contents=build_sub_content_prompt(topic, course_context, skill_path=skill["skill_path"]),
            config={
                "system_instruction": "You generate valid JSON instructional sub-content chunks only.",
                "temperature": 0.2,
                "response_mime_type": "application/json",
            },
        )
        last_raw_output = response.text or ""

        try:
            output = parse_model_response(last_raw_output)
            output = normalize_content_output(output, topic=topic)
            validate_content_output(output)
            return output
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc

    raise ContentTestStageError(
        "sub_content_generator",
        last_raw_output,
        last_error or "Unknown sub_content_generator parsing error.",
        sub_content_input,
    )


def generate_content_test_output(
    payload,
    syllabus,
    client=None,
    model_name="gemini-2.5-flash",
    output_dir=CONTENT_TEST_OUTPUT_DIR,
    max_attempts=2,
):
    if client is None:
        client = build_client()

    try:
        content = _generate_content_plan_for_content_test(
            payload,
            syllabus,
            client=client,
            model_name=model_name,
            max_attempts=max_attempts,
        )
    except ContentTestStageError as exc:
        debug_path = save_content_test_debug(
            stage_name=exc.stage_name,
            raw_model_output=exc.raw_model_output,
            error_message=exc.original_error,
            input_payload=exc.input_payload,
            output_dir=output_dir,
        )
        raise ValueError(f"Content test generation failed. Debug saved to {debug_path}") from exc.original_error

    course_context = _build_content_test_course_context(payload, syllabus)

    for topic in content.get("topics", []):
        try:
            sub_content_result = _generate_sub_contents_for_content_test_topic(
                topic=topic,
                course_context=course_context,
                client=client,
                model_name=model_name,
                max_attempts=max_attempts,
            )
        except ContentTestStageError as exc:
            debug_path = save_content_test_debug(
                stage_name=exc.stage_name,
                raw_model_output=exc.raw_model_output,
                error_message=exc.original_error,
                input_payload=exc.input_payload,
                output_dir=output_dir,
            )
            raise ValueError(f"Content test generation failed. Debug saved to {debug_path}") from exc.original_error

        topic["sub_contents"] = sub_content_result.get("sub_contents", [])
        attach_page_assessments(topic)

    output = {"content": content}
    validate_content_test_output(output)
    saved_path = save_content_test_output(output, payload=payload, output_dir=output_dir)
    return {"parsed_output": output, "saved_path": saved_path}


def generate_sub_contents_for_topic(
    topic,
    course_context,
    client=None,
    model_name="gemini-2.5-flash",
):
    if client is None:
        client = build_client()

    skill = get_skill(CONTENT_GENERATION_SKILL_NAME)
    last_error = None

    for _ in range(2):
        try:
            output = call_sub_content_generation_llm(
                topic=topic,
                course_context=course_context,
                client=client,
                model_name=model_name,
                skill_path=skill["skill_path"],
            )
            output = normalize_content_output(output, topic=topic)
            validate_content_output(output)
            return output
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc

    if os.environ.get("LEARN_ANYTHING_DEBUG") == "1":
        topic_label = topic.get("topic_title", "<unknown topic>")
        print(f"[fallback] sub_content_generator: {topic_label} ({last_error})")
    return build_fallback_sub_content_output(topic, course_context)


def add_sub_contents(output, client=None, model_name="gemini-2.5-flash"):
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
        )
        topic["sub_contents"] = sub_content_result.get("sub_contents", [])
        attach_page_assessments(topic)

    return output


def add_images(output):
    from pipeline.image_fetcher import fetch_topic_images

    for topic in output.get("content", {}).get("topics", []):
        topic["images"] = fetch_topic_images(
            topic.get("topic_title", ""),
            topic.get("topic_description", ""),
        )
    return output


_COACH_SYSTEM_INSTRUCTION = (
    "You are a concise and helpful learning coach. "
    "Help the student understand and engage with their course material."
)


def _condense_course(course):
    """Return course without lengthy sub_content text to keep coach context compact."""
    condensed = {k: v for k, v in course.items() if k != "content"}
    content = course.get("content", {})
    if content:
        condensed_topics = []
        for topic in content.get("topics", []):
            t = {k: v for k, v in topic.items() if k not in ("sub_contents", "images")}
            sub_titles = [s.get("content_title", "") for s in topic.get("sub_contents", [])]
            if sub_titles:
                t["sub_content_titles"] = sub_titles
            condensed_topics.append(t)
        condensed["content"] = {k: v for k, v in content.items() if k != "topics"}
        condensed["content"]["topics"] = condensed_topics
    return condensed


def build_coach_prompt(course, message):
    course_json = json.dumps(_condense_course(course), indent=2, ensure_ascii=False)
    return (
        f"You are a learning coach helping a student with the following course:\n\n"
        f"{course_json}\n\n"
        f"Student: {message}\n\n"
        f"Respond as a learning coach: give a direct, helpful answer. You may include "
        f"an explanation, a practical suggestion, or a follow-up question. "
        f"Keep your response under 250 words."
    )


def call_coach(course, message, client=None, model_name="gemini-2.5-flash"):
    if client is None:
        client = build_client()
    response = client.models.generate_content(
        model=model_name,
        contents=build_coach_prompt(course, message),
        config={
            "system_instruction": _COACH_SYSTEM_INSTRUCTION,
            "temperature": 0.7,
        },
    )
    return response.text.strip()


def generate_course_details(payload, syllabus, client=None, model_name="gemini-2.5-flash"):
    if client is None:
        client = build_client()

    content = generate_content_plan(payload, syllabus, client=client, model_name=model_name)
    output = merge_generated_sections(payload, syllabus, content)
    output = add_sub_contents(output, client=client, model_name=model_name)
    return add_images(output)


def generate_syllabus(payload, client=None, model_name="gemini-2.5-flash"):
    if client is None:
        client = build_client()

    syllabus = generate_syllabus_outline(payload, client=client, model_name=model_name)
    return generate_course_details(
        payload,
        syllabus,
        client=client,
        model_name=model_name,
    )


def run_content_test(
    payload,
    client=None,
    model_name="gemini-2.5-flash",
    output_dir=CONTENT_TEST_OUTPUT_DIR,
):
    if client is None:
        client = build_client()

    syllabus = generate_syllabus_outline(payload, client=client, model_name=model_name)
    result = generate_content_test_output(
        payload,
        syllabus,
        client=client,
        model_name=model_name,
        output_dir=output_dir,
    )
    return {
        "payload": payload,
        "syllabus": syllabus,
        "parsed_output": result["parsed_output"],
        "saved_path": result["saved_path"],
    }
