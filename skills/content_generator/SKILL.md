---
name: content_generator
description: Generate structured LearnAnything course content with topics, time estimates, and assessments in valid JSON.
---

# Purpose

Generate machine-readable learning content for the LearnAnything pipeline from a user learning goal or syllabus-style input. The generated output must decompose the learning goal into relevant topics, estimate study hours, and create topic-level assessments that can be consumed downstream by application code.

# When to Use

Use this skill when the input asks for a learning plan, structured content generation, topic sequencing, study time estimation, assessment planning, or syllabus-derived instructional content. Apply it when the output must be valid JSON and suitable for programmatic parsing.

# Input

The input may describe a learner goal, a syllabus request, or a structured JSON payload containing information such as:

- target skill or learning goal
- duration or time constraints
- difficulty level
- learner preferences or audience information
- syllabus-related constraints

Use only the information provided in the input. Do not invent unrelated requirements, learner traits, or extra subject areas.

# Output Format

Return JSON only with no markdown, commentary, code fences, or prose outside the JSON object.

This skill defines the structure of the nested `content` object inside a larger syllabus response.

Use this exact `content` structure:

{
"skill_name": "",
"description": "",
"difficulty_level": "",
"target_audience": "",
"topics": [
{
"topic_title": "",
"topic_description": "",
"estimated_hours": 0,
"assessment_count": 0,
"assessments": [
{
"assessment_type": "",
"assessment_description": "",
"assessment_focus": []
}
]
}
]
}

# Content Rules

1. Generate only topics that directly support the stated learning goal or syllabus input.
2. Do not include unrelated, tangential, or enrichment-only topics unless they are necessary prerequisites.
3. Each topic must include:
   - `topic_title`
   - `topic_description`
   - `estimated_hours`
   - `assessment_count`
   - `assessments`
4. Each `topic_title` must begin with a numeric prefix in the format `<week_number>.<topic_number> Topic Name`, such as `1.1 Nature of Light and Electromagnetic Spectrum` or `4.3 Space Debris Tracking and Mitigation`. Do not output unnumbered topic titles.
5. Each `estimated_hours` value must be a realistic positive number for the scope of that topic.
6. Keep the output consistent with the requested difficulty and learner context.
7. Keep wording precise, instructional, and easy to parse downstream.
8. Do not include `sub_contents` in this stage. Sub-content chunks will be generated separately later.

# Assessment Rules

1. Each topic must have at least one assessment.
2. `assessment_count` must match the actual number of objects in `assessments`.
3. Assessments must be based only on the generated topic content.
4. Each assessment should evaluate understanding, application, or synthesis of the material covered in that topic.
5. `assessment_focus` must be an array of concise concepts or skills assessed within that topic.
6. Do not create assessments for knowledge that was not introduced in the generated content.

# Quality Checks

Before returning the response, verify all of the following:

1. The response is valid JSON.
2. The response contains no markdown or explanatory text outside the JSON object.
3. Every topic has `estimated_hours`.
4. Every topic has at least one assessment.
5. `assessment_count` matches the number of generated assessments for each topic.
6. No `sub_contents` field is included anywhere in the content output.
7. Every assessment is supported by generated content only.
8. The topic list stays tightly aligned to the original learning goal or syllabus input.
