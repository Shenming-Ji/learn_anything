---
name: sub_content_generator
description: Generate instructional sub-content chunks for each course topic in valid JSON.
---

# Purpose

Generate readable instructional sub-content chunks for each topic in the LearnAnything pipeline. Each chunk should explain one focused concept, process, example, or application related to the given topic.

# When to Use

Use this skill after the `content_generator` skill has produced topic objects with `topic_title`, `topic_description`, `estimated_hours`, and assessments. This skill expands each topic into learner-facing content chunks.

# Input

The input may include:

- course topic title
- topic description
- estimated study hours
- difficulty level
- learning style
- learner preferences
- related assessments or learning objectives

Use only the provided topic and course context. Do not introduce unrelated subject areas.

# Output Format

Return JSON only with no markdown, commentary, code fences, or prose outside the JSON object.

Use this exact structure:

{
"topic_title": "",
"sub_contents": [
{
"chunk_title": "",
"chunk_text": ""
}
]
}

# Content Rules

1. Generate 2–4 `sub_contents` chunks for each topic.
2. Each `chunk_text` must be between 700 and 800 characters.
3. Each chunk must focus on one clear concept, process, example, or application.
4. The chunks must directly support the topic title and topic description.
5. Keep the content consistent with the requested difficulty level.
6. If `learning_style` is "practical", emphasize examples, applications, demonstrations, and real-world use cases.
7. If `learning_style` is "theoretical", emphasize definitions, principles, reasoning, and conceptual structure.
8. Avoid unrelated enrichment topics.
9. Do not include quiz questions or assessments in `sub_contents`.
10. Do not include citations or external links at this stage.

# Quality Checks

Before returning the response, verify all of the following:

1. The response is valid JSON.
2. Every chunk has `chunk_title` and `chunk_text`.
3. Every `chunk_text` is between 400 and 800 characters.
4. The chunks are clear, instructional, and aligned with the topic.
5. No markdown or explanatory text appears outside the JSON object.
