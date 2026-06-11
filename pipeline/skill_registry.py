from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]

SKILL_REGISTRY = {
    "content_generation": {
        "name": "content_generation",
        "version": "v1",
        "skill_file": "skills/sub_content_generator/SKILL.md",
        "input_schema": "schemas/content_input.schema.json",
        "output_schema": "schemas/content_output.schema.json",
    }
}


def get_skill(skill_name):
    if skill_name not in SKILL_REGISTRY:
        raise KeyError(f"Unknown skill: {skill_name}")

    skill = dict(SKILL_REGISTRY[skill_name])
    skill["skill_path"] = BASE_DIR / skill["skill_file"]

    input_schema = skill.get("input_schema")
    output_schema = skill.get("output_schema")
    skill["input_schema_path"] = BASE_DIR / input_schema if input_schema else None
    skill["output_schema_path"] = BASE_DIR / output_schema if output_schema else None
    return skill
