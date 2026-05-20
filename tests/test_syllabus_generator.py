import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import syllabus_generator
import syllabus_service
import content_cache_demo
import syllabus_web
from pipeline.cache_manager import make_cache_key
from pipeline.skill_registry import get_skill


class SyllabusGeneratorTests(unittest.TestCase):
    def test_skill_file_exists(self):
        self.assertTrue(syllabus_service.SKILL_PATH.exists())

    def test_reads_example_json(self):
        payload = syllabus_service.load_payload(syllabus_service.DEFAULT_INPUT_PATH)

        self.assertEqual(payload["target_skill"], "Laser and optical systems in space")
        self.assertEqual(payload["duration_weeks"], 4)

    def test_parse_model_response_strips_code_fences(self):
        text = """```json
                {"topic": "Optical Systems"}
                ```"""

        output = syllabus_service.parse_model_response(text)

        self.assertEqual(output["topic"], "Optical Systems")

    def test_parse_model_response_ignores_trailing_text_after_json(self):
        text = """{
          "topic_title": "1.1 Optical Foundations",
          "sub_contents": []
        }

        Validation note: generated successfully."""

        output = syllabus_service.parse_model_response(text)

        self.assertEqual(output["topic_title"], "1.1 Optical Foundations")

    def test_parse_model_response_finds_json_after_leading_text(self):
        text = """Here is the requested JSON:
        {
          "topic": "Optical Systems"
        }"""

        output = syllabus_service.parse_model_response(text)

        self.assertEqual(output["topic"], "Optical Systems")

    def test_normalize_content_output_fills_missing_topic_title(self):
        output = syllabus_service.normalize_content_output(
            {
                "sub_contents": [
                    {
                        "content_title": "Optical Basics",
                        "content_text": "A short explanation.",
                    }
                ]
            },
            topic={"topic_title": "1.1 Fundamentals of Optics"},
        )

        self.assertEqual(output["topic_title"], "1.1 Fundamentals of Optics")

    def test_normalize_content_output_maps_title_and_text_fields(self):
        output = syllabus_service.normalize_content_output(
            {
                "topic_title": "1.1 Fundamentals of Optics",
                "sub_contents": [
                    {
                        "title": "Optical Basics",
                        "text": "A short explanation.",
                    }
                ]
            }
        )

        chunk = output["sub_contents"][0]
        self.assertEqual(chunk["content_title"], "Optical Basics")
        self.assertEqual(chunk["content_text"], "A short explanation.")

    def test_load_system_prompt_reads_prompt_file(self):
        prompt = syllabus_service.load_system_prompt()

        self.assertIn("week-by-week course syllabus", prompt)
        self.assertIn("Do not generate the nested `content` object", prompt)

    def test_load_content_generation_skill_reads_skill_file(self):
        skill_text = syllabus_service.load_content_generation_skill()

        self.assertTrue(skill_text.strip())
        self.assertIn('"skill_name"', skill_text)
        self.assertIn("Do not include `sub_contents`", skill_text)

    def test_build_syllabus_prompt_includes_prompt_and_payload(self):
        payload = {
            "target_skill": "Intro to robotics",
            "duration_weeks": 6,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": ["Hands-on learner"],
        }

        prompt = syllabus_service.build_syllabus_prompt(payload)

        self.assertIn("week-by-week course syllabus", prompt)
        self.assertIn('"target_skill": "Intro to robotics"', prompt)
        self.assertIn("Return only the syllabus-related fields", prompt)

    def test_build_content_prompt_includes_skill_and_syllabus_context(self):
        payload = {
            "target_skill": "Intro to robotics",
            "duration_weeks": 6,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": ["Hands-on learner"],
        }
        syllabus = {
            "topic": "Intro to robotics",
            "pedagogical_style": "Hands-on and structured.",
            "goals": ["Understand core robotics concepts"],
            "syllabus": [
                {
                    "week": 1,
                    "topic": "Foundations",
                    "learning_objectives": ["Explain what a robot is"],
                    "assessments": ["Describe the main parts of a simple robot."],
                }
            ],
        }

        prompt = syllabus_service.build_content_prompt(payload, syllabus)

        self.assertIn('name: content_generator', prompt)
        self.assertIn('"target_skill": "Intro to robotics"', prompt)
        self.assertIn('"pedagogical_style": "Hands-on and structured."', prompt)
        self.assertIn("Align the topics and assessments with the provided syllabus_context", prompt)

    def test_skill_registry_exposes_content_generation_metadata(self):
        skill = get_skill("content_generation")

        self.assertEqual(skill["version"], "v1")
        self.assertTrue(skill["cacheable"])
        self.assertTrue(skill["skill_path"].exists())
        self.assertTrue(skill["input_schema_path"].exists())
        self.assertTrue(skill["output_schema_path"].exists())

    def test_make_cache_key_is_stable_for_equivalent_inputs(self):
        first_key = make_cache_key(
            "content_generation",
            "v1",
            {
                "topic_title": "Linear Regression",
                "personal_parameters": ["Prefers clear explanations"],
            },
        )
        second_key = make_cache_key(
            "content_generation",
            "v1",
            {
                "personal_parameters": ["Prefers clear explanations"],
                "topic_title": "Linear   Regression",
            },
        )

        self.assertEqual(first_key, second_key)

    def test_generate_syllabus_uses_skill_enriched_prompt(self):
        payload = {
            "target_skill": "Intro to robotics",
            "duration_weeks": 6,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": ["Hands-on learner"],
        }
        syllabus_response = SimpleNamespace(
            text=json.dumps(
                {
                    "topic": "Intro to robotics",
                    "pedagogical_style": "Hands-on and structured.",
                    "goals": ["Understand core robotics concepts"],
                    "syllabus": [
                        {
                            "week": 1,
                            "topic": "Foundations",
                            "learning_objectives": ["Explain what a robot is"],
                            "assessments": ["Describe the main parts of a simple robot."]
                        }
                    ],
                }
            )
        )
        content_response = SimpleNamespace(
            text=json.dumps(
                {
                    "skill_name": "content_generator",
                    "description": "A structured robotics content plan aligned to the syllabus.",
                    "difficulty_level": "2",
                    "target_audience": "Beginner undergraduate learners",
                    "topics": [
                        {
                            "topic_title": "1.1 Robotics Foundations",
                            "topic_description": "Introduce what robots are, how they are categorized, and the core subsystems used in simple robotic systems.",
                            "estimated_hours": 5,
                            "assessment_count": 1,
                            "assessments": [
                                {
                                    "assessment_type": "short_answer",
                                    "assessment_description": "Explain the role of sensors, actuators, and controllers in a basic robot.",
                                    "assessment_focus": ["sensors", "actuators", "controllers"]
                                }
                            ]
                        }
                    ]
                }
            )
        )
        sub_content_response = SimpleNamespace(
            text=json.dumps(
                {
                    "topic_title": "1.1 Robotics Foundations",
                    "sub_contents": [
                        {
                            "content_title": "What Makes a Robot a Robot",
                            "content_text": "Foundational explanation"
                        }
                    ]
                }
            )
        )
        captured_calls = []

        def fake_generate_content(**kwargs):
            captured_calls.append(kwargs)
            call_number = len(captured_calls)
            if call_number == 1:
                return syllabus_response
            if call_number == 2:
                return content_response
            return sub_content_response

        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                output = syllabus_service.generate_syllabus(
                    payload,
                    client=fake_client,
                    cache_dir=Path(temp_dir),
                )

        self.assertEqual(output["topic"], "Intro to robotics")
        self.assertEqual(output["duration_weeks"], 6)
        self.assertEqual(output["content"]["skill_name"], "content_generator")
        self.assertEqual(output["pedagogical_style"], "Hands-on and structured.")
        
        topics = output["content"]["topics"]
        self.assertIn("sub_contents", topics[0])
        self.assertIsInstance(topics[0]["sub_contents"], list)

        first_call = captured_calls[0]
        self.assertIn("week-by-week course syllabus", first_call["contents"])
        self.assertIn('"target_skill": "Intro to robotics"', first_call["contents"])
        self.assertEqual(first_call["config"]["system_instruction"], "You generate valid JSON syllabus plans only.")
        self.assertGreaterEqual(len(captured_calls), 3)

        second_call = captured_calls[1]
        self.assertIn("name: content_generator", second_call["contents"])
        self.assertIn('"pedagogical_style": "Hands-on and structured."', second_call["contents"])
        self.assertIn("Return JSON only", second_call["contents"])

        third_call = captured_calls[2]
        self.assertIn("sub_content_generator", third_call["contents"])
        self.assertIn("1.1 Robotics Foundations", third_call["contents"])
        self.assertIn("Return JSON only", third_call["contents"])

    def test_generate_sub_contents_for_topic_uses_cache_after_first_run(self):
        topic = {
            "topic_title": "1.1 Linear Regression",
            "topic_description": "Introduce the purpose, assumptions, and interpretation of linear regression.",
            "estimated_hours": 4,
            "assessments": [
                {
                    "assessment_type": "short_answer",
                    "assessment_description": "Explain the meaning of the regression slope.",
                    "assessment_focus": ["slope", "interpretation"],
                }
            ],
        }
        course_context = {
            "topic": "Introduction to Machine Learning",
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": ["Prefers clear explanations"],
            "goals": ["Understand supervised learning workflows"],
        }
        call_state = {"count": 0}
        fake_response = {
            "topic_title": "1.1 Linear Regression",
            "sub_contents": [
                {
                    "content_title": "Regression Intuition",
                    "content_text": "Linear regression maps how inputs relate to an output through a simple predictive relationship.",
                }
            ],
        }

        def fake_generate_content(**_):
            call_state["count"] += 1
            return SimpleNamespace(text=json.dumps(fake_response))

        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                first_output = syllabus_service.generate_sub_contents_for_topic(
                    topic=topic,
                    course_context=course_context,
                    client=fake_client,
                    cache_dir=Path(temp_dir),
                )
                second_output = syllabus_service.generate_sub_contents_for_topic(
                    topic=topic,
                    course_context=course_context,
                    client=fake_client,
                    cache_dir=Path(temp_dir),
                )

        self.assertEqual(first_output, second_output)
        self.assertEqual(call_state["count"], 1)

        logs = stdout.getvalue()
        self.assertIn("[cache miss] content_generation: 1.1 Linear Regression, calling LLM...", logs)
        self.assertIn("[cache saved] content_generation: 1.1 Linear Regression", logs)
        self.assertIn("[cache hit] content_generation: 1.1 Linear Regression", logs)

    def test_content_cache_demo_runs_sample_input_twice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                first_output, second_output = content_cache_demo.run_demo(
                    syllabus_service.DEFAULT_INPUT_PATH,
                    cache_dir=Path(temp_dir),
                )

        self.assertEqual(first_output, second_output)

        logs = stdout.getvalue()
        self.assertIn("Using input file:", logs)
        self.assertIn("Target skill: Laser and optical systems in space", logs)
        self.assertIn("---- first sub-content pass ----", logs)
        self.assertIn("[cache miss] content_generation: 1.1 Foundations of Space Optical Systems, calling LLM...", logs)
        self.assertIn("[cache hit] content_generation: 1.1 Foundations of Space Optical Systems", logs)
        self.assertIn("Second run additional model calls: syllabus=0, content_plan=0, sub_content=0", logs)
        self.assertIn("Outputs match: True", logs)

    def test_content_cache_demo_parse_args_supports_live_mode(self):
        args = content_cache_demo.parse_args(
            [
                str(syllabus_service.DEFAULT_INPUT_PATH),
                "--live",
                "--model",
                "gemini-2.5-pro",
                "--cache-dir",
                ".cache/demo",
            ]
        )

        self.assertTrue(args.live)
        self.assertEqual(args.model, "gemini-2.5-pro")
        self.assertEqual(args.cache_dir, ".cache/demo")

    def test_syllabus_web_build_payload_from_form(self):
        payload = syllabus_web.build_payload_from_form(
            {
                "target_skill": "Intro to robotics",
                "duration_weeks": "6",
                "difficulty_level": "2",
                "learning_style": "practical",
                "hours_per_week": "5",
                "personal_parameters": "Hands-on learner\nNeeds step-by-step structure",
            }
        )

        self.assertEqual(payload["target_skill"], "Intro to robotics")
        self.assertEqual(payload["duration_weeks"], 6)
        self.assertEqual(payload["difficulty_level"], 2)
        self.assertEqual(
            payload["personal_parameters"],
            ["Hands-on learner", "Needs step-by-step structure"],
        )

    def test_syllabus_web_split_personal_parameters_supports_commas_and_lines(self):
        items = syllabus_web.split_personal_parameters(
            "Prefers examples, Wants pacing help\nNeeds review checkpoints"
        )

        self.assertEqual(
            items,
            [
                "Prefers examples",
                "Wants pacing help",
                "Needs review checkpoints",
            ],
        )

    def test_syllabus_web_loads_known_sample(self):
        payload = syllabus_web.load_sample_payload("space")

        self.assertEqual(payload["target_skill"], "Laser and optical systems in space")

    def test_syllabus_web_parse_args(self):
        args = syllabus_web.parse_args(["--host", "0.0.0.0", "--port", "9000"])

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9000)

    def test_syllabus_web_html_renders_assessments_and_sub_contents(self):
        html = (Path(__file__).resolve().parents[1] / "python" / "syllabus_web.html").read_text(encoding="utf-8")

        self.assertIn("function renderAssessments", html)
        self.assertIn("function renderSubContents", html)
        self.assertIn("function summarizeText", html)
        self.assertIn("Assessment Details", html)
        self.assertIn("Sub-content Details", html)
        self.assertIn("Read full text", html)

    def test_build_tracking_client_counts_live_style_calls(self):
        captured_calls = []

        def fake_generate_content(**kwargs):
            captured_calls.append(kwargs)
            return SimpleNamespace(text=json.dumps({"ok": True}))

        base_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )
        tracking_client = content_cache_demo.build_tracking_client(base_client)

        tracking_client.models.generate_content(
            model="demo",
            contents="syllabus",
            config={"system_instruction": "You generate valid JSON syllabus plans only."},
        )
        tracking_client.models.generate_content(
            model="demo",
            contents="content",
            config={"system_instruction": "You generate valid JSON content plans only."},
        )
        tracking_client.models.generate_content(
            model="demo",
            contents="sub content",
            config={"system_instruction": "You generate valid JSON instructional sub-content chunks only."},
        )

        self.assertEqual(len(captured_calls), 3)
        self.assertEqual(tracking_client.call_state["syllabus"], 1)
        self.assertEqual(tracking_client.call_state["content_plan"], 1)
        self.assertEqual(tracking_client.call_state["sub_content"], 1)

    def test_merge_generated_sections_uses_payload_for_static_fields(self):
        payload = {
            "target_skill": "Intro to robotics",
            "duration_weeks": 6,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": ["Hands-on learner"],
        }
        syllabus = {
            "topic": "Intro to robotics",
            "pedagogical_style": "Hands-on and structured.",
            "goals": ["Understand core robotics concepts"],
            "syllabus": [{"week": 1, "topic": "Foundations", "learning_objectives": [], "assessments": []}],
        }
        content = {
            "skill_name": "content_generator",
            "description": "A structured robotics content plan aligned to the syllabus.",
            "difficulty_level": "2",
            "target_audience": "Beginner undergraduate learners",
            "topics": [],
        }

        output = syllabus_service.merge_generated_sections(payload, syllabus, content)

        self.assertEqual(output["duration_weeks"], 6)
        self.assertEqual(output["difficulty_level"], 2)
        self.assertEqual(output["content"]["skill_name"], "content_generator")
        self.assertEqual(output["pedagogical_style"], "Hands-on and structured.")

    def test_existing_public_functions_import_successfully(self):
        self.assertTrue(callable(syllabus_service.load_payload))
        self.assertTrue(callable(syllabus_service.generate_syllabus))
        self.assertTrue(callable(syllabus_generator.main))

    # test the whole pipeline
    def test_main_reads_json_file_and_prints_result(self):
        fake_response = SimpleNamespace(
            text=json.dumps(
                {
                    "topic": "Laser and optical systems in space",
                    "duration_weeks": 4,
                    "difficulty_level": 2,
                    "learning_style": "practical",
                    "hours_per_week": 6,
                    "personal_parameters": [
                        "Prefers clear and structured explanations",
                        "Needs structured step-by-step learning"
                    ],
                    "goals": ["Understand core optical components"],
                    "syllabus": [
                        {
                            "week": 1,
                            "topic": "Foundations",
                            "learning_objectives": ["Identify basic optical concepts"],
                            "assessments": ["What is the difference between reflection and refraction?"]
                        }
                    ],
                    "content": {
                        "skill_name": "content_generator",
                        "description": "A structured content plan for laser and optical systems in space.",
                        "difficulty_level": "2",
                        "target_audience": "Beginner technical learners",
                        "topics": [
                            {
                                "topic_title": "Foundations of Optical Systems",
                                "topic_description": "Cover basic optical principles and components needed to understand space-based optical systems.",
                                "estimated_hours": 6,
                                "assessment_count": 1,
                                "assessments": [
                                    {
                                        "assessment_type": "short_answer",
                                        "assessment_description": "What is the difference between reflection and refraction?",
                                        "assessment_focus": ["reflection", "refraction"]
                                    }
                                ]
                            }
                        ]
                    }
                }
            )
        )
        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **_: fake_response)
        )

        with patch.object(syllabus_generator, "generate_syllabus", return_value=json.loads(fake_response.text)):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                syllabus_generator.main([str(syllabus_service.DEFAULT_INPUT_PATH)])

        output = json.loads(stdout.getvalue())
        self.assertEqual(output["topic"], "Laser and optical systems in space")
        self.assertEqual(len(output["syllabus"]), 1)
        self.assertEqual(output["content"]["skill_name"], "content_generator")


if __name__ == "__main__":
    unittest.main()
