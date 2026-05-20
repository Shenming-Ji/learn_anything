import argparse
import copy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from syllabus_service import (
    DEFAULT_INPUT_PATH,
    add_sub_contents,
    build_client,
    generate_content_plan,
    generate_syllabus_outline,
    load_payload,
    merge_generated_sections,
)


def build_fake_client(payload):
    call_state = {
        "syllabus": 0,
        "content_plan": 0,
        "sub_content": 0,
    }

    syllabus_response = {
        "topic": payload["target_skill"],
        "pedagogical_style": "Practical, structured, and example-driven.",
        "goals": [
            f"Build a working foundation in {payload['target_skill']}",
            "Connect theory to real engineering decisions",
        ],
        "syllabus": [
            {
                "week": 1,
                "topic": "Foundations of Space Optical Systems",
                "learning_objectives": [
                    "Explain why optical systems are used in space missions",
                    "Identify the main functions of laser and optical subsystems",
                ],
                "assessments": [
                    "Summarize the role of optical payloads in a representative space mission.",
                ],
            },
            {
                "week": 2,
                "topic": "Laser Links and Operational Constraints",
                "learning_objectives": [
                    "Describe the basics of free-space optical communication",
                    "Explain how alignment and environment affect performance",
                ],
                "assessments": [
                    "Compare a laser communication link with a radio-frequency link for a mission scenario.",
                ],
            },
        ],
    }

    content_plan_response = {
        "skill_name": "content_generator",
        "description": f"A structured content plan for {payload['target_skill']}.",
        "difficulty_level": str(payload["difficulty_level"]),
        "target_audience": "Beginner technical learners",
        "topics": [
            {
                "topic_title": "1.1 Foundations of Space Optical Systems",
                "topic_description": "Introduce the purpose, architecture, and mission roles of lasers and optical subsystems in space platforms.",
                "estimated_hours": payload["hours_per_week"],
                "assessment_count": 1,
                "assessments": [
                    {
                        "assessment_type": "short_answer",
                        "assessment_description": "Explain why optical systems are valuable for sensing and communication in space missions.",
                        "assessment_focus": ["mission roles", "optical subsystems"],
                    }
                ],
            },
            {
                "topic_title": "2.1 Laser Links and Operational Constraints",
                "topic_description": "Explain free-space laser links, pointing requirements, and the environmental factors that shape system performance.",
                "estimated_hours": payload["hours_per_week"],
                "assessment_count": 1,
                "assessments": [
                    {
                        "assessment_type": "scenario_analysis",
                        "assessment_description": "Analyze which operational constraints most strongly affect a space laser link in a given mission.",
                        "assessment_focus": ["pointing", "environmental constraints"],
                    }
                ],
            },
        ],
    }

    def build_sub_content_response(topic_title):
        return {
            "topic_title": topic_title,
            "sub_contents": [
                {
                    "content_title": f"{topic_title} Overview",
                    "content_text": f"{topic_title} begins with the core ideas, the mission context, and the engineering purpose behind the topic.",
                },
                {
                    "content_title": f"{topic_title} Key Components",
                    "content_text": f"{topic_title} then breaks down the main components, constraints, and design tradeoffs that learners should recognize.",
                },
                {
                    "content_title": f"{topic_title} Practical Reasoning",
                    "content_text": f"{topic_title} is reinforced through practical reasoning about how system choices affect performance in realistic space scenarios.",
                },
                {
                    "content_title": f"{topic_title} Common Pitfalls",
                    "content_text": f"{topic_title} closes with common mistakes, operational risks, and the checks that help engineers make better decisions.",
                },
            ],
        }

    def fake_generate_content(**kwargs):
        system_instruction = kwargs.get("config", {}).get("system_instruction", "")
        prompt = kwargs.get("contents", "")

        if system_instruction == "You generate valid JSON syllabus plans only.":
            call_state["syllabus"] += 1
            return SimpleNamespace(text=json.dumps(syllabus_response))

        if system_instruction == "You generate valid JSON content plans only.":
            call_state["content_plan"] += 1
            return SimpleNamespace(text=json.dumps(content_plan_response))

        if system_instruction == "You generate valid JSON instructional sub-content chunks only.":
            call_state["sub_content"] += 1
            if "2.1 Laser Links and Operational Constraints" in prompt:
                topic_title = "2.1 Laser Links and Operational Constraints"
            else:
                topic_title = "1.1 Foundations of Space Optical Systems"
            return SimpleNamespace(text=json.dumps(build_sub_content_response(topic_title)))

        raise ValueError(f"Unexpected system instruction: {system_instruction}")

    return SimpleNamespace(
        models=SimpleNamespace(generate_content=fake_generate_content),
        call_state=call_state,
    )


def build_tracking_client(base_client):
    call_state = {
        "syllabus": 0,
        "content_plan": 0,
        "sub_content": 0,
    }

    def tracked_generate_content(**kwargs):
        system_instruction = kwargs.get("config", {}).get("system_instruction", "")

        if system_instruction == "You generate valid JSON syllabus plans only.":
            call_state["syllabus"] += 1
        elif system_instruction == "You generate valid JSON content plans only.":
            call_state["content_plan"] += 1
        elif system_instruction == "You generate valid JSON instructional sub-content chunks only.":
            call_state["sub_content"] += 1

        return base_client.models.generate_content(**kwargs)

    return SimpleNamespace(
        models=SimpleNamespace(generate_content=tracked_generate_content),
        call_state=call_state,
    )


def build_demo_client(payload, use_live):
    if use_live:
        return build_tracking_client(build_client())

    return build_fake_client(payload)


def run_demo(input_path, cache_dir=None, use_live=False, model_name="gemini-2.5-flash"):
    input_path = Path(input_path)
    payload = load_payload(input_path)
    demo_client = build_demo_client(payload, use_live=use_live)

    if cache_dir is not None:
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        return _run_demo_with_cache_dir(
            payload,
            demo_client,
            cache_path,
            input_path=input_path,
            persistent_cache=True,
            use_live=use_live,
            model_name=model_name,
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        return _run_demo_with_cache_dir(
            payload,
            client=demo_client,
            cache_dir=Path(temp_dir),
            input_path=input_path,
            persistent_cache=False,
            use_live=use_live,
            model_name=model_name,
        )


def _run_demo_with_cache_dir(payload, client, cache_dir, input_path, persistent_cache, use_live, model_name):
    print(f"Using input file: {input_path}")
    print(f"Target skill: {payload.get('target_skill')}")
    print(f"Mode: {'live Gemini client' if use_live else 'fake client'}")
    print(f"Model: {model_name}")
    print(f"Cache directory: {cache_dir}")
    if not persistent_cache:
        print("Cache directory is temporary and will be removed after the demo.")
    if use_live:
        print("Live mode reuses the same syllabus/content plan for both passes so we can isolate topic-level sub-content caching.")

    syllabus = generate_syllabus_outline(
        payload,
        client=client,
        model_name=model_name,
    )
    content = generate_content_plan(
        payload,
        syllabus,
        client=client,
        model_name=model_name,
    )
    base_output = merge_generated_sections(payload, syllabus, content)

    print("---- first sub-content pass ----")
    first_output = add_sub_contents(
        copy.deepcopy(base_output),
        client=client,
        cache_dir=cache_dir,
        model_name=model_name,
    )
    first_run_counts = dict(client.call_state)

    print("---- second sub-content pass ----")
    second_output = add_sub_contents(
        copy.deepcopy(base_output),
        client=client,
        cache_dir=cache_dir,
        model_name=model_name,
    )
    second_run_counts = {
        name: client.call_state[name] - first_run_counts[name]
        for name in client.call_state
    }

    print(f"Outputs match: {first_output == second_output}")
    print(
        "First run model calls: "
        f"syllabus={first_run_counts['syllabus']}, "
        f"content_plan={first_run_counts['content_plan']}, "
        f"sub_content={first_run_counts['sub_content']}"
    )
    print(
        "Second run additional model calls: "
        f"syllabus={second_run_counts['syllabus']}, "
        f"content_plan={second_run_counts['content_plan']}, "
        f"sub_content={second_run_counts['sub_content']}"
    )
    print(
        "Total model calls: "
        f"syllabus={client.call_state['syllabus']}, "
        f"content_plan={client.call_state['content_plan']}, "
        f"sub_content={client.call_state['sub_content']}"
    )

    return first_output, second_output


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the sample-input cache demo for the syllabus pipeline."
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        default=str(DEFAULT_INPUT_PATH),
        help="Path to a sample input JSON file. Defaults to python/inputs/space.json.",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory to keep after the script exits.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the real Gemini client instead of the built-in fake client.",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Model name used for live runs. Defaults to gemini-2.5-flash.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    run_demo(
        args.input_path,
        cache_dir=args.cache_dir,
        use_live=args.live,
        model_name=args.model,
    )


if __name__ == "__main__":
    main()
