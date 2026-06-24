import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import content_test_generator
import content_test_viewer
import syllabus_generator
import syllabus_service
import syllabus_web
from pipeline.image_fetcher import (
    _build_query,
    _clean_topic_title,
    _extract_key_terms,
    _is_relevant,
    fetch_topic_images,
)
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

    def test_parse_model_response_repairs_latex_backslashes_in_json_strings(self):
        text = """{
          "topic_title": "3.1 Making Sense of Predictions",
          "sub_contents": [
            {
              "content_title": "Residuals",
              "content_text": "Residuals can be written as \\(y_{actual} - y_{predicted}\\) and sometimes displayed as \\[e = y - \\hat{y}\\]."
            }
          ]
        }"""

        # Simulate model output with invalid JSON escapes like \( and \[
        text = text.replace("\\\\(", "\\(").replace("\\\\[", "\\[").replace("\\\\h", "\\h")

        output = syllabus_service.parse_model_response(text)

        content_text = output["sub_contents"][0]["content_text"]
        self.assertIn("\\(y_{actual} - y_{predicted}\\)", content_text)
        self.assertIn("\\[e = y - \\hat{y}\\]", content_text)

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

    def test_normalize_content_output_accepts_contents_alias(self):
        output = syllabus_service.normalize_content_output(
            {
                "topic_title": "1.1 Fundamentals of Optics",
                "contents": [
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

    def test_normalize_content_output_wraps_single_top_level_content_into_lesson_list(self):
        output = syllabus_service.normalize_content_output(
            {
                "topic_title": "1.1 Fundamentals of Optics",
                "content_title": "Optical Basics",
                "content_text": "A short explanation.",
            }
        )

        self.assertEqual(output["sub_contents"][0]["content_title"], "Optical Basics")
        self.assertEqual(output["sub_contents"][0]["content_text"], "A short explanation.")

    def test_normalize_content_output_wraps_top_level_list(self):
        output = syllabus_service.normalize_content_output(
            [
                {
                    "title": "Optical Basics",
                    "text": "A short explanation.",
                }
            ]
        )

        self.assertEqual(output["sub_contents"][0]["content_title"], "Optical Basics")
        self.assertEqual(output["sub_contents"][0]["content_text"], "A short explanation.")

    def test_normalize_content_output_accepts_pages_alias(self):
        output = syllabus_service.normalize_content_output(
            {
                "topic_title": "1.1 Fundamentals of Optics",
                "pages": [
                    {
                        "lesson_title": "Optical Basics",
                        "description": "A short explanation.",
                    }
                ],
            }
        )

        self.assertEqual(output["sub_contents"][0]["content_title"], "Optical Basics")
        self.assertEqual(output["sub_contents"][0]["content_text"], "A short explanation.")

    def test_normalize_outline_output_wraps_top_level_list(self):
        payload = {"target_skill": "Intro to robotics"}

        output = syllabus_service.normalize_outline_output(
            [
                {
                    "week": 1,
                    "topic": "Foundations",
                    "learning_objectives": [],
                    "assessments": [],
                }
            ],
            payload=payload,
        )

        self.assertEqual(output["topic"], "Intro to robotics")
        self.assertEqual(len(output["syllabus"]), 1)
        self.assertEqual(output["goals"], [])

    def test_load_system_prompt_reads_prompt_file(self):
        prompt = syllabus_service.load_system_prompt()

        self.assertIn("week-by-week course syllabus", prompt)
        self.assertIn("Do not generate the nested `content` object", prompt)

    def test_load_content_generation_skill_reads_skill_file(self):
        skill_text = syllabus_service.load_content_generation_skill()

        self.assertTrue(skill_text.strip())
        self.assertIn('"skill_name"', skill_text)
        self.assertIn("Do not include `sub_contents`", skill_text)

    def test_sub_content_skill_includes_formula_format_guidance(self):
        skill_text = syllabus_service.load_sub_content_generation_skill()

        self.assertIn("\\(...\\)", skill_text)
        self.assertIn("\\[...\\]", skill_text)
        self.assertIn("Do not wrap formulas in code fences", skill_text)

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

    def test_build_syllabus_prompt_includes_regeneration_guidance(self):
        payload = {
            "target_skill": "Intro to robotics",
            "duration_weeks": 6,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": [],
        }

        prompt = syllabus_service.build_syllabus_prompt(
            payload,
            outline_feedback="Make the syllabus more project-based.",
            regenerate=True,
        )

        self.assertIn("Additional syllabus guidance", prompt)
        self.assertIn("Make the syllabus more project-based.", prompt)

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
        self.assertIn("topic_description should preview the most useful instructional elements", prompt)

    def test_build_sub_content_prompt_includes_content_quality_guidance(self):
        topic = {
            "topic_title": "1.1 Linear Regression Foundations",
            "topic_description": "Introduce the purpose of linear regression.",
            "estimated_hours": 4,
            "assessments": [],
        }
        course_context = {
            "topic": "Linear regression for beginners",
            "difficulty_level": 2,
            "learning_style": "practical",
        }

        prompt = syllabus_service.build_sub_content_prompt(topic, course_context)

        self.assertIn("decide whether formulas, worked examples, graph descriptions, tables, code examples", prompt)
        self.assertIn("escape backslashes correctly inside JSON strings", prompt)

    def test_generate_content_test_output_uses_original_pipeline_and_saves_merged_json(self):
        payload = {
            "target_skill": "Linear regression for beginners",
            "duration_weeks": 4,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": ["Prefers intuitive explanations"],
        }
        syllabus = {
            "topic": "Linear regression for beginners",
            "pedagogical_style": "Practical and step-by-step.",
            "goals": ["Understand how linear regression models relationships in data."],
            "syllabus": [
                {
                    "week": 1,
                    "topic": "Regression foundations",
                    "learning_objectives": ["Explain what a best-fit line represents."],
                    "assessments": ["Interpret the slope in a simple regression example."],
                }
            ],
        }
        content_response = {
            "skill_name": "content_generator",
            "description": "A beginner-friendly linear regression content plan.",
            "difficulty_level": "2",
            "target_audience": "Beginner learners",
            "topics": [
                {
                    "topic_title": "1.1 Linear Regression Foundations",
                    "topic_description": "Introduce the purpose, assumptions, and interpretation of linear regression.",
                    "estimated_hours": 4,
                    "assessment_count": 1,
                    "assessments": [
                        {
                            "assessment_type": "multiple_choice",
                            "assessment_description": "What does the slope represent in a simple linear regression model?",
                            "choices": [
                                "A. The prediction when the input is zero",
                                "B. The average prediction error",
                                "C. The change in the prediction for a one-unit increase in the input",
                                "D. The number of observations in the dataset",
                            ],
                            "correct_answer": "C",
                            "assessment_focus": ["slope", "interpretation"],
                        }
                    ],
                }
            ],
        }
        sub_content_response = {
            "topic_title": "1.1 Linear Regression Foundations",
            "sub_contents": [
                {
                    "content_title": "Why Linear Regression Matters",
                    "content_text": "This lesson explains why a simple best-fit line helps summarize relationships in small, real-world datasets.",
                },
                {
                    "content_title": "Slope and Intercept",
                    "content_text": "This lesson explains how the slope captures rate of change and how the intercept anchors the fitted line.",
                },
                {
                    "content_title": "Model Assumptions",
                    "content_text": "This lesson outlines when a linear model is a reasonable approximation and what residual patterns can reveal.",
                },
                {
                    "content_title": "Reading Results in Practice",
                    "content_text": "This lesson connects fitted coefficients to concrete business or scientific interpretations.",
                },
            ],
        }
        call_state = {"count": 0}

        def fake_generate_content(**_):
            call_state["count"] += 1
            if call_state["count"] == 1:
                return SimpleNamespace(text=json.dumps(content_response))
            return SimpleNamespace(text=json.dumps(sub_content_response))

        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )

        with TemporaryDirectory() as tmpdir:
            result = syllabus_service.generate_content_test_output(
                payload,
                syllabus,
                client=fake_client,
                output_dir=Path(tmpdir),
            )

            saved_path = result["saved_path"]
            saved_output = json.loads(saved_path.read_text(encoding="utf-8"))

        self.assertEqual(call_state["count"], 2)
        self.assertIn("content", result["parsed_output"])
        self.assertEqual(saved_output, result["parsed_output"])
        self.assertNotIn("learning_objectives", result["parsed_output"])
        topic = result["parsed_output"]["content"]["topics"][0]
        self.assertEqual(topic["topic_title"], "1.1 Linear Regression Foundations")
        self.assertEqual(len(topic["sub_contents"]), 4)
        self.assertIn("page_assessment", topic["sub_contents"][0])

    def test_generate_content_test_output_saves_debug_file_on_sub_content_failure(self):
        payload = {
            "target_skill": "Linear regression for beginners",
            "duration_weeks": 4,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": [],
        }
        syllabus = {
            "topic": "Linear regression for beginners",
            "pedagogical_style": "Practical and step-by-step.",
            "goals": ["Understand how linear regression models relationships in data."],
            "syllabus": [],
        }
        content_response = {
            "skill_name": "content_generator",
            "description": "A beginner-friendly linear regression content plan.",
            "difficulty_level": "2",
            "target_audience": "Beginner learners",
            "topics": [
                {
                    "topic_title": "1.1 Linear Regression Foundations",
                    "topic_description": "Introduce the purpose, assumptions, and interpretation of linear regression.",
                    "estimated_hours": 4,
                    "assessment_count": 1,
                    "assessments": [
                        {
                            "assessment_type": "multiple_choice",
                            "assessment_description": "What does the slope represent in a simple linear regression model?",
                            "choices": [
                                "A. The prediction when the input is zero",
                                "B. The average prediction error",
                                "C. The change in the prediction for a one-unit increase in the input",
                                "D. The number of observations in the dataset",
                            ],
                            "correct_answer": "C",
                            "assessment_focus": ["slope", "interpretation"],
                        }
                    ],
                }
            ],
        }
        invalid_sub_content_response = {
            "topic_title": "1.1 Linear Regression Foundations",
            "sub_contents": [],
        }
        call_state = {"count": 0}

        def fake_generate_content(**_):
            call_state["count"] += 1
            if call_state["count"] == 1:
                return SimpleNamespace(text=json.dumps(content_response))
            return SimpleNamespace(text=json.dumps(invalid_sub_content_response))

        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )

        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError) as exc:
                syllabus_service.generate_content_test_output(
                    payload,
                    syllabus,
                    client=fake_client,
                    output_dir=Path(tmpdir),
                )

            debug_files = list(Path(tmpdir).glob("*_debug.json"))
            self.assertEqual(len(debug_files), 1)
            debug_payload = json.loads(debug_files[0].read_text(encoding="utf-8"))

        self.assertIn("Debug saved to", str(exc.exception))
        self.assertEqual(call_state["count"], 3)
        self.assertEqual(debug_payload["stage_name"], "sub_content_generator")
        self.assertIn("raw_model_output", debug_payload)
        self.assertIn("error_message", debug_payload)
        self.assertIn("input_payload", debug_payload)
        self.assertIn("timestamp", debug_payload)

    def test_skill_registry_exposes_content_generation_metadata(self):
        skill = get_skill("content_generation")

        self.assertEqual(skill["version"], "v1")
        self.assertTrue(skill["skill_path"].exists())
        self.assertTrue(skill["input_schema_path"].exists())
        self.assertTrue(skill["output_schema_path"].exists())

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

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            output = syllabus_service.generate_syllabus(
                payload,
                client=fake_client,
            )

        self.assertEqual(output["topic"], "Intro to robotics")
        self.assertEqual(output["duration_weeks"], 6)
        self.assertEqual(output["content"]["skill_name"], "content_generator")
        self.assertEqual(output["pedagogical_style"], "Hands-on and structured.")
        
        topics = output["content"]["topics"]
        self.assertIn("sub_contents", topics[0])
        self.assertIsInstance(topics[0]["sub_contents"], list)
        self.assertIn("page_assessment", topics[0]["sub_contents"][0])

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

    def test_build_outline_preview_uses_payload_and_syllabus_fields(self):
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

        preview = syllabus_service.build_outline_preview(payload, syllabus)

        self.assertEqual(preview["topic"], "Intro to robotics")
        self.assertEqual(preview["duration_weeks"], 6)
        self.assertEqual(preview["pedagogical_style"], "Hands-on and structured.")
        self.assertNotIn("content", preview)

    def test_build_outline_preview_accepts_list_outline(self):
        payload = {
            "target_skill": "Intro to robotics",
            "duration_weeks": 6,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": [],
        }

        preview = syllabus_service.build_outline_preview(
            payload,
            [{"week": 1, "topic": "Foundations", "learning_objectives": [], "assessments": []}],
        )

        self.assertEqual(preview["topic"], "Intro to robotics")
        self.assertEqual(len(preview["syllabus"]), 1)

    def test_generate_course_details_uses_existing_outline(self):
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

        with patch.object(syllabus_service, "generate_content_plan", return_value=content) as generate_content_mock, \
             patch.object(syllabus_service, "add_sub_contents", side_effect=lambda output, **_: output) as add_sub_contents_mock, \
             patch.object(syllabus_service, "add_images", side_effect=lambda output: output) as add_images_mock:
            output = syllabus_service.generate_course_details(payload, syllabus, client=object())

        generate_content_mock.assert_called_once()
        add_sub_contents_mock.assert_called_once()
        add_images_mock.assert_called_once()
        self.assertEqual(output["content"]["skill_name"], "content_generator")
        self.assertEqual(output["topic"], "Intro to robotics")

    def test_generate_sub_contents_for_topic_calls_llm_and_normalizes_output(self):
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
                },
                {
                    "content_title": "Slope and Intercept",
                    "content_text": "The slope captures how much the prediction changes when the input increases by one unit.",
                },
                {
                    "content_title": "Model Assumptions",
                    "content_text": "Linear regression works best when the relationship is approximately linear and the residual pattern is stable.",
                },
                {
                    "content_title": "Practical Interpretation",
                    "content_text": "Interpreting a fitted line means connecting coefficients back to the real-world meaning of the variables.",
                },
            ],
        }

        def fake_generate_content(**_):
            call_state["count"] += 1
            return SimpleNamespace(text=json.dumps(fake_response))

        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )

        output = syllabus_service.generate_sub_contents_for_topic(
            topic=topic,
            course_context=course_context,
            client=fake_client,
        )

        self.assertEqual(call_state["count"], 1)
        self.assertEqual(output["topic_title"], "1.1 Linear Regression")
        self.assertEqual(output["sub_contents"][0]["content_title"], "Regression Intuition")

    def test_generate_sub_contents_for_topic_falls_back_when_model_returns_empty(self):
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
            "sub_contents": [],
        }

        def fake_generate_content(**_):
            call_state["count"] += 1
            return SimpleNamespace(text=json.dumps(fake_response))

        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )

        output = syllabus_service.generate_sub_contents_for_topic(
            topic=topic,
            course_context=course_context,
            client=fake_client,
        )

        self.assertEqual(call_state["count"], 2)
        self.assertEqual(output["topic_title"], "1.1 Linear Regression")
        self.assertEqual(len(output["sub_contents"]), 4)
        self.assertTrue(output["sub_contents"][0]["content_title"])
        self.assertTrue(output["sub_contents"][0]["content_text"])
        self.assertNotIn("1.1", output["sub_contents"][0]["content_title"])
        self.assertNotIn("1.1", output["sub_contents"][0]["content_text"].split(". ")[0])

    def test_generate_sub_contents_for_topic_falls_back_when_model_returns_too_few_lessons(self):
        topic = {
            "topic_title": "1.1 Linear Regression",
            "topic_description": "Introduce the purpose, assumptions, and interpretation of linear regression.",
            "estimated_hours": 4,
            "assessments": [],
        }
        course_context = {
            "topic": "Introduction to Machine Learning",
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": [],
            "goals": ["Understand supervised learning workflows"],
        }
        fake_response = {
            "topic_title": "1.1 Linear Regression",
            "sub_contents": [
                {
                    "content_title": "Regression Intuition",
                    "content_text": "A useful explanation.",
                }
            ],
        }

        def fake_generate_content(**_):
            return SimpleNamespace(text=json.dumps(fake_response))

        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )

        output = syllabus_service.generate_sub_contents_for_topic(
            topic=topic,
            course_context=course_context,
            client=fake_client,
        )

        self.assertEqual(len(output["sub_contents"]), syllabus_service.MIN_SUB_CONTENTS_PER_TOPIC)
        self.assertNotEqual(output["sub_contents"][0]["content_title"], "Regression Intuition")

    def test_attach_page_assessments_assigns_relevant_question_to_each_page(self):
        topic = {
            "assessments": [
                {
                    "assessment_type": "multiple_choice",
                    "assessment_description": "Which statement best describes wavelength?",
                    "choices": ["A. Color", "B. Spatial period", "C. Brightness", "D. Power"],
                    "correct_answer": "B",
                    "assessment_focus": ["wavelength"],
                },
                {
                    "assessment_type": "multiple_choice",
                    "assessment_description": "Why is polarization useful in imaging?",
                    "choices": ["A. It removes noise", "B. It reveals surface properties", "C. It slows light", "D. It changes vacuum pressure"],
                    "correct_answer": "B",
                    "assessment_focus": ["polarization"],
                },
            ],
            "sub_contents": [
                {
                    "content_title": "Working with Wavelength",
                    "content_text": "Wavelength determines how optical sensors interact with targets and the atmosphere.",
                },
                {
                    "content_title": "Understanding Polarization",
                    "content_text": "Polarization helps distinguish materials and surface reflections in remote sensing.",
                },
            ],
        }

        syllabus_service.attach_page_assessments(topic)

        self.assertEqual(topic["sub_contents"][0]["page_assessment"]["assessment_focus"], ["wavelength"])
        self.assertEqual(topic["sub_contents"][1]["page_assessment"]["assessment_focus"], ["polarization"])
        self.assertNotEqual(
            topic["sub_contents"][0]["page_assessment"]["assessment_description"],
            topic["sub_contents"][1]["page_assessment"]["assessment_description"],
        )

    def test_syllabus_web_build_payload_from_form(self):
        payload = syllabus_web.build_payload_from_form(
            {
                "target_skill": "Intro to robotics",
                "duration_weeks": "6",
                "difficulty_level": "2",
                "learning_style": "practical",
                "hours_per_week": "5",
            }
        )

        self.assertEqual(payload["target_skill"], "Intro to robotics")
        self.assertEqual(payload["duration_weeks"], 6)
        self.assertEqual(payload["difficulty_level"], 2)
        self.assertEqual(payload["personal_parameters"], [])

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
        self.assertIn("function renderLessons", html)
        self.assertIn("function buildLessonLabel", html)
        self.assertIn("function summarizeText", html)
        self.assertIn("function renderMarkdownText", html)
        self.assertIn("typesetMath", html)
        self.assertIn("MathJax", html)
        self.assertIn("tex-svg.js", html)
        self.assertIn("math-block", html)
        self.assertIn("Lesson Details", html)
        self.assertIn("Lessons", html)
        self.assertIn("Lesson ${escapeHtml(buildLessonLabel", html)
        self.assertIn('normalized.match(/^(\\d+(?:\\.\\d+)*)\\b/)', html)
        self.assertIn("Quiz", html)
        self.assertIn("data-page-completed", html)
        self.assertIn("Optional practice", html)
        self.assertIn("changeLessonPage", html)
        self.assertNotIn("Assessment Details", html)

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
        self.assertTrue(callable(content_test_generator.main))
        self.assertTrue(callable(content_test_viewer.main))

    def test_content_test_generator_main_supports_input_and_save_only(self):
        payload = {"target_skill": "Linear regression for beginners"}
        saved_path = Path("/tmp/linear_regression_2026-06-23_1530.json")
        parsed_output = {
            "content": {
                "skill_name": "content_generator",
                "description": "desc",
                "difficulty_level": "2",
                "target_audience": "Beginners",
                "topics": [
                    {
                        "topic_title": "1.1 Topic",
                        "topic_description": "desc",
                        "estimated_hours": 1,
                        "assessment_count": 1,
                        "assessments": [{"assessment_type": "true_false"}],
                        "sub_contents": [
                            {
                                "content_title": "Lesson 1",
                                "content_text": "alpha beta gamma delta epsilon zeta",
                                "page_assessment": {"assessment_type": "true_false"},
                            }
                        ],
                    }
                ],
            }
        }

        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(content_test_generator, "load_payload", return_value=payload) as load_payload_mock, \
             patch.object(
                 content_test_generator,
                 "run_content_test",
                 return_value={"parsed_output": parsed_output, "saved_path": saved_path},
             ) as run_content_test_mock, \
             redirect_stdout(stdout), \
             redirect_stderr(stderr):
            exit_code = content_test_generator.main(
                ["--input", "python/inputs/linear_regression_content_test.json", "--save-only"]
            )

        self.assertEqual(exit_code, 0)
        load_payload_mock.assert_called_once()
        run_content_test_mock.assert_called_once()
        self.assertEqual(stdout.getvalue(), "")
        stderr_text = stderr.getvalue()
        self.assertIn(f"saved_path: {saved_path}", stderr_text)
        self.assertIn("topics: 1", stderr_text)
        self.assertIn("total_sub_contents: 1", stderr_text)
        self.assertIn("every_sub_content_has_page_assessment: True", stderr_text)
        self.assertIn("minimum_content_text_word_count: 6", stderr_text)
        self.assertIn("assessment_count_matches: True", stderr_text)

    def test_summarize_content_test_output_reports_validation_metrics(self):
        output = {
            "content": {
                "topics": [
                    {
                        "assessment_count": 1,
                        "assessments": [{"assessment_type": "true_false"}],
                        "sub_contents": [
                            {
                                "content_text": "one two three four",
                                "page_assessment": {"assessment_type": "true_false"},
                            },
                            {
                                "content_text": "one two three four five six",
                                "page_assessment": {"assessment_type": "multiple_choice"},
                            },
                        ],
                    }
                ]
            }
        }

        summary = syllabus_service.summarize_content_test_output(output)

        self.assertEqual(summary["topic_count"], 1)
        self.assertEqual(summary["total_sub_contents"], 2)
        self.assertTrue(summary["every_sub_content_has_page_assessment"])
        self.assertEqual(summary["minimum_content_text_word_count"], 4)
        self.assertTrue(summary["assessment_count_matches"])

    def test_content_test_viewer_detects_quality_signals(self):
        text = (
            "A helpful scatter plot would place x-axis values against y-axis values.\n"
            "Use \\(y = mx + b\\) for the formula.\n"
            "| x | y |\n|---|---|\n| 1 | 2 |\n"
            "A standard introductory textbook or documentation reference would help.\n"
            "import pandas as pd\nmodel.fit(X, y)\n"
        )

        signals = content_test_viewer.detect_content_signals(text)

        self.assertTrue(signals["formula"])
        self.assertTrue(signals["code"])
        self.assertTrue(signals["table"])
        self.assertTrue(signals["visual"])
        self.assertTrue(signals["citation"])

    def test_content_test_viewer_normalizes_backticked_math(self):
        text = (
            r"`\(\hat{y}_i\)` and `\[ RSS = \sum_{i=1}^{n} (y_i - \hat{y}_i)^2 \]` "
            r"and `$x + y$` and `$$x^2$$`"
        )

        normalized = content_test_viewer._normalize_math_markdown(text)

        self.assertIn(r"\(\hat{y}_i\)", normalized)
        self.assertIn(r"\[ RSS = \sum_{i=1}^{n} (y_i - \hat{y}_i)^2 \]", normalized)
        self.assertIn(r"$x + y$", normalized)
        self.assertIn(r"$$x^2$$", normalized)
        self.assertNotIn(r"`\(\hat{y}_i\)`", normalized)

    def test_content_test_viewer_builds_preview_html_with_debug_indicators(self):
        payload = {
            "content": {
                "skill_name": "Linear Regression Preview",
                "description": "Debug preview",
                "difficulty_level": "2",
                "target_audience": "Beginners",
                "topics": [
                    {
                        "topic_title": "1.1 Topic",
                        "topic_description": "Includes scatter plot interpretation.",
                        "estimated_hours": 5,
                        "assessment_count": 1,
                        "assessments": [
                            {
                                "assessment_type": "multiple_choice",
                                "assessment_description": "Question",
                                "choices": ["A. One", "B. Two", "C. Three", "D. Four"],
                                "correct_answer": "A",
                                "assessment_focus": ["interpretation"],
                            }
                        ],
                        "sub_contents": [
                            {
                                "content_title": "Lesson One",
                                "content_text": "**Residual** explanation.\n\n`\\(e_i\\)` and `\\[ RSS = \\sum_(i=1)^n (y_i - \\hat{{y}}_i)^2 \\]`\n\nA helpful scatter plot with x-axis and y-axis. \\(y = mx + b\\)\n\n|a|b|\n|---|---|\n|1|2|\n\n```python\nimport pandas as pd\nmodel.fit(X, y)\n```\n\ntextbook reference",
                                "page_assessment": {
                                    "assessment_type": "true_false",
                                    "assessment_description": "Statement",
                                    "choices": ["True", "False"],
                                    "correct_answer": "True",
                                    "assessment_focus": ["lesson check"],
                                },
                            }
                        ],
                    }
                ],
            }
        }

        html = content_test_viewer.build_preview_html(payload, "sample.json")

        self.assertIn("Linear Regression Preview", html)
        self.assertIn("Words:", html)
        self.assertIn("Formula:", html)
        self.assertIn("Code:", html)
        self.assertIn("Table:", html)
        self.assertIn("Visual:", html)
        self.assertIn("Citation/source:", html)
        self.assertIn("Page Assessment", html)
        self.assertIn("content_text under 600 words", html)
        self.assertIn("sample.json", html)
        self.assertIn("<strong>Residual</strong>", html)
        self.assertIn('<table class="markdown-table">', html)
        self.assertIn('<pre class="code-block"><code class="language-python">', html)
        self.assertIn("cdn.jsdelivr.net/npm/mathjax", html)
        self.assertIn(r"\(e_i\)", html)
        self.assertNotIn("<code>\\(e_i\\)</code>", html)
        self.assertIn("MathJax.typesetPromise()", html)

    def test_content_test_viewer_main_generates_html_preview(self):
        payload = {
            "content": {
                "skill_name": "Linear Regression Preview",
                "description": "Debug preview",
                "difficulty_level": "2",
                "target_audience": "Beginners",
                "topics": [],
            }
        }

        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "preview_input.json"
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            output_path = input_path.with_name("preview_input_preview.html")

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = content_test_viewer.main(["--input", str(input_path)])

            self.assertEqual(exit_code, 0)
            self.assertIn(str(output_path), stderr.getvalue())
            self.assertTrue(output_path.exists())

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
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                syllabus_generator.main([str(syllabus_service.DEFAULT_INPUT_PATH)])

        output = json.loads(stdout.getvalue())
        self.assertIn("Generating syllabus from", stderr.getvalue())
        self.assertEqual(output["topic"], "Laser and optical systems in space")
        self.assertEqual(len(output["syllabus"]), 1)
        self.assertEqual(output["content"]["skill_name"], "content_generator")


class ImageFetcherTests(unittest.TestCase):
    def test_clean_topic_title_removes_numeric_prefix(self):
        self.assertEqual(_clean_topic_title("1.1 Foundations of Optical Systems"), "Foundations of Optical Systems")
        self.assertEqual(_clean_topic_title("3.2 Space Debris Tracking"), "Space Debris Tracking")

    def test_clean_topic_title_leaves_unprefixed_titles_unchanged(self):
        self.assertEqual(_clean_topic_title("Optical Systems"), "Optical Systems")
        self.assertEqual(_clean_topic_title(""), "")

    def test_fetch_topic_images_returns_empty_list_on_network_error(self):
        with patch("pipeline.image_fetcher.urllib.request.urlopen", side_effect=OSError("network error")):
            result = fetch_topic_images("1.1 Optical Foundations")
        self.assertEqual(result, [])

    def test_fetch_topic_images_returns_empty_list_for_empty_title(self):
        result = fetch_topic_images("")
        self.assertEqual(result, [])

    def test_fetch_topic_images_returns_correct_structure(self):
        search_response = json.dumps({
            "query": {
                "search": [
                    {"title": "Optics"},
                    {"title": "Lens"},
                ]
            }
        }).encode()
        thumbnail_response = json.dumps({
            "query": {
                "pages": {
                    "1": {
                        "title": "Optics",
                        "thumbnail": {"source": "https://upload.wikimedia.org/optics.jpg"},
                    },
                    "2": {
                        "title": "Lens",
                        "thumbnail": {"source": "https://upload.wikimedia.org/lens.jpg"},
                    },
                }
            }
        }).encode()

        call_state = {"count": 0}

        class FakeResponse:
            def __init__(self, data):
                self._data = data
            def read(self):
                return self._data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=None):
            call_state["count"] += 1
            if call_state["count"] == 1:
                return FakeResponse(search_response)
            return FakeResponse(thumbnail_response)

        with patch("pipeline.image_fetcher.urllib.request.urlopen", side_effect=fake_urlopen):
            result = fetch_topic_images("1.1 Optical Foundations", max_images=3)

        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        for image in result:
            self.assertIn("image_title", image)
            self.assertIn("image_url", image)
            self.assertTrue(image["image_url"].startswith("https://"))

    def test_fetch_topic_images_respects_max_images_limit(self):
        search_response = json.dumps({
            "query": {
                "search": [{"title": f"Page {i}"} for i in range(5)]
            }
        }).encode()
        pages = {
            str(i): {
                "title": f"Page {i}",
                "thumbnail": {"source": f"https://upload.wikimedia.org/page{i}.jpg"},
            }
            for i in range(5)
        }
        thumbnail_response = json.dumps({"query": {"pages": pages}}).encode()

        call_state = {"count": 0}

        class FakeResponse:
            def __init__(self, data):
                self._data = data
            def read(self):
                return self._data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=None):
            call_state["count"] += 1
            if call_state["count"] == 1:
                return FakeResponse(search_response)
            return FakeResponse(thumbnail_response)

        with patch("pipeline.image_fetcher.urllib.request.urlopen", side_effect=fake_urlopen):
            result = fetch_topic_images("Some Topic", max_images=2)

        self.assertLessEqual(len(result), 2)

    def test_fetch_topic_images_skips_pages_without_thumbnails(self):
        search_response = json.dumps({
            "query": {"search": [{"title": "No Image Page"}, {"title": "Has Image"}]}
        }).encode()
        thumbnail_response = json.dumps({
            "query": {
                "pages": {
                    "1": {"title": "No Image Page"},
                    "2": {
                        "title": "Has Image",
                        "thumbnail": {"source": "https://upload.wikimedia.org/img.jpg"},
                    },
                }
            }
        }).encode()

        call_state = {"count": 0}

        class FakeResponse:
            def __init__(self, data):
                self._data = data
            def read(self):
                return self._data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=None):
            call_state["count"] += 1
            if call_state["count"] == 1:
                return FakeResponse(search_response)
            return FakeResponse(thumbnail_response)

        with patch("pipeline.image_fetcher.urllib.request.urlopen", side_effect=fake_urlopen):
            result = fetch_topic_images("Some Topic")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["image_title"], "Has Image")

    def test_add_images_injects_images_field_into_each_topic(self):
        output = {
            "content": {
                "topics": [
                    {"topic_title": "1.1 Optical Foundations"},
                    {"topic_title": "1.2 Laser Systems"},
                ]
            }
        }

        def fake_fetch(topic_title, topic_description="", max_images=3):
            return [{"image_title": "Mock", "image_url": "https://upload.wikimedia.org/mock.jpg"}]

        with patch("pipeline.image_fetcher.fetch_topic_images", side_effect=fake_fetch):
            result = syllabus_service.add_images(output)

        for topic in result["content"]["topics"]:
            self.assertIn("images", topic)
            self.assertIsInstance(topic["images"], list)

    def test_add_images_is_safe_when_content_has_no_topics(self):
        output = {"content": {}}
        result = syllabus_service.add_images(output)
        self.assertIn("content", result)

    def test_extract_key_terms_removes_stopwords_and_short_tokens(self):
        terms = _extract_key_terms("the optical systems and a laser")
        self.assertIn("optical", terms)
        self.assertIn("systems", terms)
        self.assertIn("laser", terms)
        self.assertNotIn("the", terms)
        self.assertNotIn("and", terms)
        self.assertNotIn("a", terms)

    def test_build_query_combines_title_and_description(self):
        q = _build_query("1.1 Optical Foundations", "Cover basic principles of optics")
        self.assertIn("Optical Foundations", q)
        self.assertIn("Cover basic principles", q)
        self.assertNotIn("1.1", q)

    def test_build_query_uses_only_title_when_no_description(self):
        q = _build_query("1.1 Optical Foundations")
        self.assertEqual(q, "Optical Foundations")

    def test_build_query_strips_numeric_prefix(self):
        self.assertEqual(_build_query("3.2 Space Debris"), "Space Debris")

    def test_is_relevant_accepts_root_matched_terms(self):
        # "optical" and "optics" share root "optic"
        self.assertTrue(_is_relevant("Optics", {"optical", "systems"}))

    def test_is_relevant_rejects_disambiguation_pages(self):
        self.assertFalse(_is_relevant("Optics (disambiguation)", {"optical"}))

    def test_is_relevant_rejects_titles_with_no_shared_root(self):
        self.assertFalse(_is_relevant("History of ancient Rome", {"optical", "laser", "space"}))

    def test_is_relevant_accepts_exact_match(self):
        self.assertTrue(_is_relevant("Laser", {"laser", "space"}))

    def test_fetch_topic_images_passes_description_to_query(self):
        queries_seen = []

        search_response = json.dumps({"query": {"search": []}}).encode()

        class FakeResponse:
            def __init__(self, data):
                self._data = data
            def read(self):
                return self._data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=None):
            queries_seen.append(req.full_url)
            return FakeResponse(search_response)

        with patch("pipeline.image_fetcher.urllib.request.urlopen", side_effect=fake_urlopen):
            fetch_topic_images("1.1 Optical Foundations", "Cover basic optical principles")

        self.assertTrue(len(queries_seen) > 0)
        self.assertIn("Optical+Foundations", queries_seen[0].replace("%20", "+").replace(" ", "+"))

    def test_add_images_passes_description_to_fetcher(self):
        output = {
            "content": {
                "topics": [
                    {"topic_title": "1.1 Laser Systems", "topic_description": "Introduction to lasers"},
                ]
            }
        }
        calls = []

        def fake_fetch(topic_title, topic_description="", max_images=3):
            calls.append((topic_title, topic_description))
            return []

        with patch("pipeline.image_fetcher.fetch_topic_images", side_effect=fake_fetch):
            syllabus_service.add_images(output)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "1.1 Laser Systems")
        self.assertEqual(calls[0][1], "Introduction to lasers")

    def test_syllabus_web_html_contains_render_images_function(self):
        html = (Path(__file__).resolve().parents[1] / "python" / "syllabus_web.html").read_text(encoding="utf-8")
        self.assertIn("function renderImages", html)
        self.assertIn("image-grid", html)
        self.assertIn("image-card", html)
        self.assertIn("image_url", html)
        self.assertIn("image_title", html)


class CoachTests(unittest.TestCase):
    def _sample_course(self):
        return {
            "topic": "Machine Learning",
            "duration_weeks": 4,
            "difficulty_level": 2,
            "goals": ["Understand supervised learning"],
            "syllabus": [
                {
                    "week": 1,
                    "topic": "Linear Regression",
                    "learning_objectives": ["Explain the regression line"],
                    "assessments": ["Describe the slope of a regression."],
                }
            ],
            "content": {
                "topics": [
                    {
                        "topic_title": "1.1 Linear Regression",
                        "topic_description": "Intro to regression.",
                        "estimated_hours": 4,
                        "assessments": [{"assessment_type": "short_answer", "assessment_description": "Explain slope.", "assessment_focus": ["slope"]}],
                        "sub_contents": [
                            {"content_title": "Regression Intuition", "content_text": "A" * 800}
                        ],
                        "images": [{"image_title": "Scatter plot", "image_url": "https://upload.wikimedia.org/scatter.jpg"}],
                    }
                ]
            },
        }

    def test_condense_course_removes_sub_content_text(self):
        course = self._sample_course()
        condensed = syllabus_service._condense_course(course)
        topic = condensed["content"]["topics"][0]
        self.assertNotIn("sub_contents", topic)
        self.assertNotIn("images", topic)
        self.assertIn("sub_content_titles", topic)
        self.assertEqual(topic["sub_content_titles"], ["Regression Intuition"])

    def test_condense_course_keeps_top_level_fields(self):
        course = self._sample_course()
        condensed = syllabus_service._condense_course(course)
        self.assertEqual(condensed["topic"], "Machine Learning")
        self.assertEqual(condensed["goals"], ["Understand supervised learning"])
        self.assertIn("syllabus", condensed)

    def test_build_coach_prompt_includes_message_and_course(self):
        course = self._sample_course()
        prompt = syllabus_service.build_coach_prompt(course, "Explain linear regression simply")
        self.assertIn("linear regression", prompt.lower())
        self.assertIn("Machine Learning", prompt)
        self.assertIn("learning coach", prompt.lower())

    def test_build_coach_prompt_does_not_include_full_sub_content_text(self):
        course = self._sample_course()
        prompt = syllabus_service.build_coach_prompt(course, "Help me")
        self.assertNotIn("A" * 800, prompt)

    def test_call_coach_returns_model_reply(self):
        course = self._sample_course()
        fake_response = SimpleNamespace(text="  Linear regression fits a line to your data.  ")
        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **_: fake_response)
        )
        reply = syllabus_service.call_coach(course, "Explain linear regression", client=fake_client)
        self.assertEqual(reply, "Linear regression fits a line to your data.")

    def test_call_coach_passes_prompt_with_course_and_message(self):
        course = self._sample_course()
        captured = {}

        def fake_generate(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text="ok")

        fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate))
        syllabus_service.call_coach(course, "Quiz me on Week 1", client=fake_client)

        self.assertIn("Quiz me on Week 1", captured["contents"])
        self.assertIn("Machine Learning", captured["contents"])

    def test_web_handler_coach_returns_reply(self):
        fake_reply = "Great question! Linear regression..."

        with patch.object(syllabus_web, "call_coach", return_value=fake_reply):
            handler = syllabus_web.SyllabusWebHandler.__new__(syllabus_web.SyllabusWebHandler)
            sent = {}

            def fake_send_json(data, status=200):
                sent["data"] = data
                sent["status"] = status

            handler._send_json = fake_send_json
            handler.headers = {"Content-Length": "0"}

            body = json.dumps({"course": {"topic": "ML"}, "message": "Explain it"}).encode()
            handler.rfile = io.BytesIO(body)
            handler.headers = {"Content-Length": str(len(body))}
            handler._handle_coach()

        self.assertEqual(sent["data"]["reply"], fake_reply)

    def test_web_handler_coach_rejects_missing_message(self):
        handler = syllabus_web.SyllabusWebHandler.__new__(syllabus_web.SyllabusWebHandler)
        sent = {}

        def fake_send_json(data, status=200):
            sent["data"] = data
            sent["status"] = status

        handler._send_json = fake_send_json
        body = json.dumps({"course": {}, "message": "  "}).encode()
        handler.rfile = io.BytesIO(body)
        handler.headers = {"Content-Length": str(len(body))}
        handler._handle_coach()

        self.assertIn("error", sent["data"])

    def test_web_handler_generate_outline_returns_preview(self):
        outline = {
            "topic": "ML",
            "pedagogical_style": "Practical and structured.",
            "goals": ["Understand regression"],
            "syllabus": [{"week": 1, "topic": "Linear Regression", "learning_objectives": [], "assessments": []}],
        }
        preview = {
            "topic": "ML",
            "duration_weeks": 4,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": [],
            "pedagogical_style": "Practical and structured.",
            "goals": ["Understand regression"],
            "syllabus": [{"week": 1, "topic": "Linear Regression", "learning_objectives": [], "assessments": []}],
        }

        with patch.object(syllabus_web, "generate_syllabus_outline", return_value=outline), \
             patch.object(syllabus_web, "build_outline_preview", return_value=preview):
            handler = syllabus_web.SyllabusWebHandler.__new__(syllabus_web.SyllabusWebHandler)
            sent = {}

            def fake_send_json(data, status=200):
                sent["data"] = data
                sent["status"] = status

            handler._send_json = fake_send_json
            body = json.dumps({
                "target_skill": "ML",
                "duration_weeks": 4,
                "difficulty_level": 2,
                "learning_style": "practical",
                "hours_per_week": 5,
                "personal_parameters": [],
            }).encode()
            handler.rfile = io.BytesIO(body)
            handler.headers = {"Content-Length": str(len(body))}
            handler._generate_outline()

        self.assertEqual(sent["status"], 200)
        self.assertEqual(sent["data"]["syllabus"], outline)
        self.assertEqual(sent["data"]["output"], preview)

    def test_web_handler_start_outline_task_returns_task_id(self):
        fake_task = {
            "task_id": "outline-task-1",
            "kind": "outline",
            "state": "queued",
            "progress": 0,
            "message": "Queued outline generation...",
            "error": None,
            "result": None,
        }

        with patch.object(syllabus_web, "start_outline_task", return_value=fake_task) as start_outline_task_mock:
            handler = syllabus_web.SyllabusWebHandler.__new__(syllabus_web.SyllabusWebHandler)
            sent = {}

            def fake_send_json(data, status=200):
                sent["data"] = data
                sent["status"] = status

            handler._send_json = fake_send_json
            body = json.dumps({
                "target_skill": "ML",
                "duration_weeks": 4,
                "difficulty_level": 2,
                "learning_style": "practical",
                "hours_per_week": 5,
                "outline_feedback": "Make it more hands-on.",
                "regenerate_outline": True,
            }).encode()
            handler.rfile = io.BytesIO(body)
            handler.headers = {"Content-Length": str(len(body))}
            handler._start_outline_task()

        self.assertEqual(sent["status"], 202)
        self.assertEqual(sent["data"]["task_id"], "outline-task-1")
        start_outline_task_mock.assert_called_once_with(
            {
                "target_skill": "ML",
                "duration_weeks": 4,
                "difficulty_level": 2,
                "learning_style": "practical",
                "hours_per_week": 5,
                "personal_parameters": [],
            },
            outline_feedback="Make it more hands-on.",
            regenerate=True,
        )

    def test_web_handler_generate_details_requires_syllabus(self):
        handler = syllabus_web.SyllabusWebHandler.__new__(syllabus_web.SyllabusWebHandler)
        sent = {}

        def fake_send_json(data, status=200):
            sent["data"] = data
            sent["status"] = status

        handler._send_json = fake_send_json
        body = json.dumps({
            "payload": {
                "target_skill": "ML",
                "duration_weeks": 4,
                "difficulty_level": 2,
                "learning_style": "practical",
                "hours_per_week": 5,
                "personal_parameters": [],
            }
        }).encode()
        handler.rfile = io.BytesIO(body)
        handler.headers = {"Content-Length": str(len(body))}
        handler._generate_details()

        self.assertEqual(sent["status"], 400)
        self.assertIn("syllabus", sent["data"]["error"])

    def test_web_handler_generate_details_returns_full_output(self):
        fake_output = {
            "topic": "ML",
            "duration_weeks": 4,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": [],
            "pedagogical_style": "Practical and structured.",
            "goals": ["Understand regression"],
            "syllabus": [{"week": 1, "topic": "Linear Regression", "learning_objectives": [], "assessments": []}],
            "content": {"topics": []},
        }

        with patch.object(syllabus_web, "generate_course_details", return_value=fake_output):
            handler = syllabus_web.SyllabusWebHandler.__new__(syllabus_web.SyllabusWebHandler)
            sent = {}

            def fake_send_json(data, status=200):
                sent["data"] = data
                sent["status"] = status

            handler._send_json = fake_send_json
            body = json.dumps({
                "payload": {
                    "target_skill": "ML",
                    "duration_weeks": 4,
                    "difficulty_level": 2,
                    "learning_style": "practical",
                    "hours_per_week": 5,
                    "personal_parameters": [],
                },
                "syllabus": {
                    "topic": "ML",
                    "pedagogical_style": "Practical and structured.",
                    "goals": ["Understand regression"],
                    "syllabus": [{"week": 1, "topic": "Linear Regression", "learning_objectives": [], "assessments": []}],
                },
            }).encode()
            handler.rfile = io.BytesIO(body)
            handler.headers = {"Content-Length": str(len(body))}
            handler._generate_details()

        self.assertEqual(sent["status"], 200)
        self.assertEqual(sent["data"]["output"], fake_output)

    def test_web_handler_start_details_task_returns_task_id(self):
        fake_task = {
            "task_id": "details-task-1",
            "kind": "details",
            "state": "queued",
            "progress": 0,
            "message": "Queued full course generation...",
            "error": None,
            "result": None,
        }

        with patch.object(syllabus_web, "start_details_task", return_value=fake_task):
            handler = syllabus_web.SyllabusWebHandler.__new__(syllabus_web.SyllabusWebHandler)
            sent = {}

            def fake_send_json(data, status=200):
                sent["data"] = data
                sent["status"] = status

            handler._send_json = fake_send_json
            body = json.dumps({
                "payload": {
                    "target_skill": "ML",
                    "duration_weeks": 4,
                    "difficulty_level": 2,
                    "learning_style": "practical",
                    "hours_per_week": 5,
                    "personal_parameters": [],
                },
                "syllabus": {
                    "topic": "ML",
                    "pedagogical_style": "Practical and structured.",
                    "goals": ["Understand regression"],
                    "syllabus": [{"week": 1, "topic": "Linear Regression", "learning_objectives": [], "assessments": []}],
                },
            }).encode()
            handler.rfile = io.BytesIO(body)
            handler.headers = {"Content-Length": str(len(body))}
            handler._start_details_task()

        self.assertEqual(sent["status"], 202)
        self.assertEqual(sent["data"]["task_id"], "details-task-1")

    def test_web_handler_task_status_returns_task_snapshot(self):
        task = {
            "task_id": "task-123",
            "kind": "outline",
            "state": "running",
            "progress": 35,
            "message": "Outline generated. Preparing preview...",
            "error": None,
            "result": None,
        }
        syllabus_web.TASKS["task-123"] = task

        try:
            handler = syllabus_web.SyllabusWebHandler.__new__(syllabus_web.SyllabusWebHandler)
            sent = {}

            def fake_send_json(data, status=200):
                sent["data"] = data
                sent["status"] = status

            handler._send_json = fake_send_json
            handler._serve_task_status("/api/tasks/task-123")
        finally:
            syllabus_web.TASKS.clear()

        self.assertEqual(sent["status"], 200)
        self.assertEqual(sent["data"]["task_id"], "task-123")
        self.assertEqual(sent["data"]["progress"], 35)

    def test_build_coach_prompt_with_mc_assessments(self):
        course = self._sample_course()
        course["content"]["topics"][0]["assessments"] = [{
            "assessment_type": "multiple_choice",
            "assessment_description": "What does slope represent?",
            "choices": ["A. Intercept", "B. Rate of change", "C. Variance", "D. Mean"],
            "correct_answer": "B",
            "assessment_focus": ["slope"],
        }]
        prompt = syllabus_service.build_coach_prompt(course, "Quiz me")
        self.assertIn("Quiz me", prompt)
        self.assertIn("Rate of change", prompt)

    def test_syllabus_web_html_contains_coach_panel(self):
        html = (Path(__file__).resolve().parents[1] / "python" / "syllabus_web.html").read_text(encoding="utf-8")
        self.assertIn("coach-panel", html)
        self.assertIn("coach-messages", html)
        self.assertIn("coach-toggle", html)
        self.assertIn("setCoachCollapsed", html)
        self.assertIn("sendCoachMessage", html)
        self.assertIn("changeLessonPage", html)
        self.assertIn("lesson-pager", html)
        self.assertIn("review-actions", html)
        self.assertIn("generateCourseDetails", html)
        self.assertIn("/api/generate-outline-async", html)
        self.assertIn("/api/generate-details-async", html)
        self.assertIn("/api/tasks/", html)
        self.assertIn("waitForTask", html)
        self.assertIn("setCoachCollapsed(true);", html)
        self.assertIn('if (generateButton.disabled) return;', html)
        self.assertIn('generateButton.setAttribute("aria-busy", "true")', html)
        self.assertIn("status-progress", html)
        self.assertIn("status-progress-fill", html)
        self.assertIn("setProgress(", html)
        self.assertIn("outline-feedback", html)
        self.assertIn("Extra Syllabus Guidance", html)
        self.assertNotIn("personal-parameters", html)
        self.assertNotIn("outputJson.textContent", html)
        self.assertIn("Learning Coach", html)
        self.assertIn("/coach", html)
        self.assertNotIn("input-preview", html)
        self.assertNotIn("output-json", html)
        self.assertNotIn("Input JSON Preview", html)
        self.assertNotIn("Final JSON", html)


class QuizRenderingTests(unittest.TestCase):
    def _html(self):
        return (Path(__file__).resolve().parents[1] / "python" / "syllabus_web.html").read_text(encoding="utf-8")

    def test_content_generator_skill_supports_multiple_quiz_formats(self):
        skill_text = (Path(__file__).resolve().parents[1] / "skills" / "content_generator" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("multiple_choice", skill_text)
        self.assertIn("true_false", skill_text)
        self.assertIn("matching", skill_text)
        self.assertIn('"choices"', skill_text)
        self.assertIn('"correct_answer"', skill_text)
        self.assertIn('"matching_pairs"', skill_text)
        self.assertIn('"match_options"', skill_text)

    def test_content_generator_skill_quality_checks_include_matching(self):
        skill_text = (Path(__file__).resolve().parents[1] / "skills" / "content_generator" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("correct_answer", skill_text)
        self.assertIn("matching", skill_text.lower())
        self.assertIn("true_false", skill_text)

    def test_html_renders_mc_choices_when_present(self):
        html = self._html()
        self.assertIn("renderMcChoices", html)
        self.assertIn("mc-choices", html)
        self.assertIn("mc-correct", html)
        self.assertIn("mc-wrong", html)

    def test_html_renders_matching_quiz_when_present(self):
        html = self._html()
        self.assertIn("renderMatchingQuiz", html)
        self.assertIn("checkMatchingAnswer", html)
        self.assertIn("matching-grid", html)
        self.assertIn("matching-select", html)

    def test_html_uses_lesson_and_quiz_labels(self):
        html = self._html()
        self.assertIn("Lesson Details", html)
        self.assertIn("Lesson ${escapeHtml(buildLessonLabel", html)
        self.assertIn("Quizzes", html)
        self.assertIn("<h3>Quiz</h3>", html)

    def test_html_has_interactive_quiz_handlers(self):
        html = self._html()
        self.assertIn("handleMcAnswer", html)
        self.assertIn("checkMatchingAnswer", html)
        self.assertIn("dataset.answered", html)
        self.assertIn("markLessonCompleted(pagerId, currentIndex);", html)
        self.assertNotIn('currentLesson && currentLesson.dataset.pageCompleted !== "true"', html)

    def test_html_backward_compat_check_for_choices(self):
        html = self._html()
        self.assertIn("Array.isArray(assessment.choices)", html)
        self.assertIn('assessment.assessment_type === "matching"', html)
        self.assertIn('assessment.assessment_type === "true_false"', html)

    def test_topic_card_does_not_render_duplicate_assessment_section(self):
        html = self._html()
        self.assertNotIn("Assessment Details", html)

    def test_coach_panel_is_on_left(self):
        html = self._html()
        self.assertIn("left: 16px", html)
        idx = html.index("left: 16px")
        nearby = html[max(0, idx - 100): idx + 50]
        self.assertIn("coach", nearby.lower())


if __name__ == "__main__":
    unittest.main()
