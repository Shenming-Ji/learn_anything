import os
import json
from pathlib import Path
from google import genai

DEFAULT_GOOGLE_CREDENTIALS = Path(__file__).resolve().parents[1] / "google-api-key.json"
if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and DEFAULT_GOOGLE_CREDENTIALS.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(DEFAULT_GOOGLE_CREDENTIALS)

SYSTEM_PROMPT = """You are an expert curriculum designer and instructional architect.

Task:
Given a JSON input, generate a week-by-week course syllabus that teaches the target skill.

Input (JSON):
{
  "target_skill": string,
  "duration_weeks": integer,
  "difficulty_level": integer (1-5),
  "learning_style": string ("practical" or "theoretical"),
  "hours_per_week": integer,
  "personal_parameters": array of strings
}

Difficulty mapping:
1 = High school
2 = Undergraduate introductory
3 = Undergraduate advanced / Bachelor level
4 = Master's level
5 = PhD / research level

Strict rules:
1) You MUST follow the JSON fields exactly. Do not assume missing fields.
2) Output MUST be valid JSON ONLY. Do NOT include markdown, backticks, or code fences.
3) Each syllabus must include:
   - "topic": short descriptive title of the course
   - "pedagogical_style": 1-2 sentences describing the teaching approach
   - "goals": a list of learning objectives for the course
   - "syllabus": an array of each weekly topics that must align with the goals
     Each week object must include:
       - "week": integer
       - "topic": short title
       - "learning_objectives": array of strings ( at most 5 )
       - "assessments": array of questions to assess each learning objective
5) Personalization:
   Use "personal_parameters" to tailor examples, activities, or mini-project themes (without being overly personal).
6) Keep scope consistent with "difficulty_level" and "duration_weeks".
7) Use "learning_style" to shape the syllabus:
    - If "practical", emphasize applications, labs, demonstrations, engineering examples, and hands-on activities.
    - If "theoretical", emphasize concepts, principles, frameworks, and deeper conceptual understanding.
8) Use "hours_per_week" to keep the weekly workload realistic and appropriately scoped.
9) Each week must include assessments to evaluate each learning objective.
10) Week 1 and Week 2 must be very foundational.
    Assume the learner has no prior knowledge of the subject.
    Begin with fundamentals and avoid unexplained advanced concepts in the first two weeks.


Return JSON in this exact top-level structure:
{
  "topic": "...",
  "duration_weeks": ...,
  "difficulty_level": ...,
  "learning_style": "...",
  "hours_per_week": ...,
  "personal_parameters": [ ... ],
  "goals": [ ... ],
  "syllabus": [ ... ]
}
"""

def main():
    # 1) Prepare JSON input
    payload = {
        "target_skill": "Laser and optical systems in space",
        "duration_weeks": 4,
        "difficulty_level": 2,
        "learning_style": "practical",
        "hours_per_week": 6,
        "personal_parameters": [
            "Prefers clear and structured explanations",
            "Needs structured step-by-step learning"
        ]
    }

    client = genai.Client(
        vertexai=True,
        project="mcc-ece-gemini",
        location="us-central1"
    )

    model_name = "gemini-2.5-flash"

    response = client.models.generate_content(
        model=model_name,
        contents=json.dumps(payload),
        config={
            "system_instruction": SYSTEM_PROMPT,
            "temperature": 0.3,
        },
    )

    text = response.text.strip()

    # In case the model still adds code fences, strip them defensively
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    # print("=== RAW MODEL OUTPUT START ===")
    # print(text)
    # print("=== RAW MODEL OUTPUT END ===")

    output = json.loads(text)

    # 5) Print pretty JSON
    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
