---
name: sub_content_generator
description: Generate instructional sub-content contents for each course topic in valid JSON.
---

# Purpose

Generate readable instructional sub-content contents for each topic in the LearnAnything pipeline. Each content should explain one focused concept, process, example, or application related to the given topic.

# When to Use

Use this skill after the `content_generator` skill has produced topic objects with `topic_title`, `topic_description`, `estimated_hours`, and assessments. This skill expands each topic into learner-facing content contents.

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
"content_title": "",
"content_text": ""
}
]
}

# Content Rules

1. Generate at least 4 `sub_contents` contents for each topic.
2. Each `content_text` must be 600+ words.
3. Each content must focus on one clear concept, process, example, or application.
4. The contents must directly support the topic title and topic description.
5. Keep the content consistent with the requested difficulty level.
6. If `learning_style` is "practical", emphasize examples, applications, demonstrations, and real-world use cases.
7. If `learning_style` is "theoretical", emphasize definitions, principles, reasoning, and conceptual structure.
8. Avoid unrelated enrichment topics.
9. Do not include quiz questions or assessments in `sub_contents`.
10. Do not include citations or external links at this stage.
11. If a formula is needed, write it in LaTeX notation using `\(...\)` for inline math and `\[...\]` for display math.
12. Do not wrap formulas in code fences, backticks, markdown tables, or pseudo-ASCII art.
13. Keep formulas embedded naturally within the explanatory text so they read like part of the lesson, not a detached markdown artifact.
14. Decide actively whether each content should include formulas, worked examples, graph descriptions, table descriptions, code examples, media or image guidance, or source recommendations based on the topic and learner context. Include these naturally inside `content_text` only when they genuinely help learning.
15. If graphs or visual explanations would help, describe what the graph or visual should show and what the learner should notice.
16. If tables would help, include a small markdown-style table only when it improves clarity and fits naturally in the lesson. Otherwise describe the comparison or dataset clearly in prose.
17. If code would help, include a short learner-facing example, preferably in Python unless the input suggests otherwise, and explain what the code is doing.
18. If images or media would help, describe the asset and explain why it would support understanding.
19. If a citation or source recommendation would help, mention the type of source naturally in the lesson text without inventing exact URLs or bibliographic details.
20. Avoid repeating the same introductory framing across multiple contents or across later topics in the course.
21. Make later contents build on prior course context when appropriate instead of reintroducing the entire topic from scratch.
22. Because the response must be valid JSON, escape backslashes correctly inside JSON strings. For LaTeX, output JSON-safe sequences such as `\\(`, `\\)`, `\\[`, and `\\]`.

# Quality Checks

Before returning the response, verify all of the following:

1. The response is valid JSON.
2. Every content has `content_title` and `content_text`.
3. Every `content_text` is must be 600+ words.
4. The contents are clear, instructional, and aligned with the topic.
5. No markdown or explanatory text appears outside the JSON object.
6. When formulas, graphs, tables, code, media guidance, or source recommendations are included, they are relevant to the topic and embedded naturally inside `content_text`.
