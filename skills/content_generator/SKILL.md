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
"assessment_type": "multiple_choice",
"assessment_description": "<question stem>",
"choices": [
"A. <first option>",
"B. <second option>",
"C. <third option>",
"D. <fourth option>"
],
"correct_answer": "<A, B, C, or D>",
"assessment_focus": []
},
{
"assessment_type": "true_false",
"assessment_description": "<statement to judge>",
"choices": [
"True",
"False"
],
"correct_answer": "<True or False>",
"assessment_focus": []
},
{
"assessment_type": "matching",
"assessment_description": "<matching prompt>",
"matching_pairs": [
{
"prompt": "<left-side item>",
"match": "<correct right-side item>"
}
],
"match_options": [
"<right-side option 1>",
"<right-side option 2>"
],
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
9. Use `topic_description` to signal what learners will actually study in the topic, including whether the topic naturally calls for formulas, worked examples, visual interpretation, graphs, tables, code examples, media or images, or citation-style source recommendations.
10. Do not create new schema fields for content requirements. If a topic needs formulas, graphs, tables, code, media, or source guidance, mention those needs naturally inside `description`, `target_audience`, and especially `topic_description`.
11. For mathematical or quantitative topics, make `topic_description` mention the formulas, calculations, and interpretation tasks learners should expect.
12. For data-analysis topics, make `topic_description` mention visual interpretation tasks such as scatter plots, trend lines, comparison tables, or model-output reading when relevant.
13. For programming or implementation-oriented topics, make `topic_description` mention concise learner-facing code usage when relevant.
14. Keep later topics progressive so they build on earlier topics instead of restarting the course from scratch.

# Assessment Rules

1. Each topic must have at least one assessment.
2. `assessment_count` must match the actual number of objects in `assessments`.
3. Use a mix of supported quiz types when it improves learning variety. Supported `assessment_type` values are `"multiple_choice"`, `"true_false"`, and `"matching"`.
4. For `"multiple_choice"`, include exactly four choices labeled `"A. ..."`, `"B. ..."`, `"C. ..."`, `"D. ..."`.
5. For `"multiple_choice"`, `correct_answer` must be exactly one of `"A"`, `"B"`, `"C"`, or `"D"`, and must correspond to the correct choice in `choices`.
6. For `"true_false"`, include `choices` as `["True", "False"]` and set `correct_answer` to either `"True"` or `"False"`.
7. For `"matching"`, include `matching_pairs` with at least three prompt-match pairs. Also include `match_options` containing the right-side options needed to solve the match.
8. Assessments must be based only on the generated topic content.
9. Each assessment should evaluate understanding, application, or synthesis of the material covered in that topic.
10. `assessment_focus` must be an array of concise concepts or skills assessed within that topic.
11. Do not create assessments for knowledge that was not introduced in the generated content.
12. Prefer assessments that reflect the likely instructional elements of the topic. For example, formula-based topics should assess interpretation or calculation, data-analysis topics should assess graph or table reading, and implementation-oriented topics should assess code understanding or workflow reasoning when relevant.
13. Avoid repeating nearly identical assessments across multiple topics.
14. Make the assessment mix feel purposeful rather than generic. Use question formats that fit the skill being practiced in that topic.

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
9. Every assessment has a supported `assessment_type`.
10. Every `"multiple_choice"` assessment has exactly four `choices` strings labeled A through D.
11. Every `"multiple_choice"` `correct_answer` is one of `"A"`, `"B"`, `"C"`, `"D"` and matches the correct choice.
12. Every `"true_false"` assessment uses `choices` of `["True", "False"]`.
13. Every `"matching"` assessment includes valid `matching_pairs` and `match_options`.
14. Every topic description clearly previews the kinds of learner-facing instructional elements the downstream sub-content stage should elaborate.
