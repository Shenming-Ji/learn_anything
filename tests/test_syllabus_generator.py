import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import syllabus_generator
import syllabus_service


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

    def test_load_system_prompt_reads_prompt_file(self):
        prompt = syllabus_service.load_system_prompt()

        self.assertIn("week-by-week course syllabus", prompt)
        self.assertIn("nested `content` object", prompt)

    def test_load_content_generation_skill_reads_skill_file(self):
        skill_text = syllabus_service.load_content_generation_skill()

        self.assertTrue(skill_text.strip())
        self.assertIn('"skill_name"', skill_text)
        self.assertIn("Do not include `sub_contents`", skill_text)

    def test_build_generation_prompt_includes_skill_prompt_and_payload(self):
        payload = {
            "target_skill": "Intro to robotics",
            "duration_weeks": 6,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": ["Hands-on learner"],
        }

        prompt = syllabus_service.build_generation_prompt(payload)

        self.assertIn('name: content_generator', prompt)
        self.assertIn("Existing syllabus prompt:", prompt)
        self.assertIn("week-by-week course syllabus", prompt)
        self.assertIn('"target_skill": "Intro to robotics"', prompt)
        self.assertIn("nested content object", prompt)

    def test_generate_syllabus_uses_skill_enriched_prompt(self):
        payload = {
            "target_skill": "Intro to robotics",
            "duration_weeks": 6,
            "difficulty_level": 2,
            "learning_style": "practical",
            "hours_per_week": 5,
            "personal_parameters": ["Hands-on learner"],
        }
        fake_response = SimpleNamespace(
            text=json.dumps(
                {
                    "topic": "Intro to robotics",
                    "duration_weeks": 6,
                    "difficulty_level": 2,
                    "learning_style": "practical",
                    "hours_per_week": 5,
                    "personal_parameters": ["Hands-on learner"],
                    "goals": ["Understand core robotics concepts"],
                    "syllabus": [
                        {
                            "week": 1,
                            "topic": "Foundations",
                            "learning_objectives": ["Explain what a robot is"],
                            "assessments": ["Describe the main parts of a simple robot."]
                        }
                    ],
                    "content": {
                        "skill_name": "content_generator",
                        "description": "A structured robotics content plan aligned to the syllabus.",
                        "difficulty_level": "2",
                        "target_audience": "Beginner undergraduate learners",
                        "topics": [
                            {
                                "topic_title": "Robotics Foundations",
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
                }
            )
        )
        captured_call = {}

        def fake_generate_content(**kwargs):
            captured_call.update(kwargs)
            return fake_response

        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )

        output = syllabus_service.generate_syllabus(payload, client=fake_client)

        self.assertEqual(output["topic"], "Intro to robotics")
        self.assertEqual(output["content"]["skill_name"], "content_generator")
        self.assertNotIn("sub_contents", json.dumps(output["content"]))
        self.assertIn("name: content_generator", captured_call["contents"])
        self.assertIn('"target_skill": "Intro to robotics"', captured_call["contents"])
        self.assertEqual(
            captured_call["config"]["system_instruction"],
            syllabus_service.load_system_prompt(),
        )

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
