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
                    ]
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


if __name__ == "__main__":
    unittest.main()
