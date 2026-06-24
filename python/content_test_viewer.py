import argparse
import json
import re
import sys
from html import escape
from pathlib import Path


DEFAULT_WORD_COUNT_THRESHOLD = 600
VISUAL_TERMS = (
    "scatter plot",
    "graph",
    "visual",
    "axis",
    "axes",
    "residual plot",
    "trend line",
    "plot",
    "diagram",
)
CITATION_TERMS = (
    "textbook",
    "documentation",
    "source",
    "reference",
    "citation",
    "scikit-learn",
    "standard introductory",
)
CODE_TERMS = (
    "import ",
    "def ",
    "model.fit",
    "plt.",
    "pd.",
    "python",
    "print(",
    "linearregression(",
    "sklearn",
)


def load_content_test_json(input_path):
    with open(input_path, "r", encoding="utf-8") as file:
        return json.load(file)


def count_words(text):
    return len(re.findall(r"\b\S+\b", str(text or "")))


def detect_content_signals(text):
    normalized = str(text or "")
    lowered = normalized.lower()

    has_formula = any(token in normalized for token in (r"\(", r"\[", "$"))
    has_code = "```" in normalized or any(term in lowered for term in CODE_TERMS)
    has_table = any(line.count("|") >= 2 for line in normalized.splitlines())
    has_visual = any(term in lowered for term in VISUAL_TERMS)
    has_citation = any(term in lowered for term in CITATION_TERMS)

    return {
        "formula": has_formula,
        "code": has_code,
        "table": has_table,
        "visual": has_visual,
        "citation": has_citation,
    }


def summarize_topic(topic):
    assessments = topic.get("assessments", []) if isinstance(topic, dict) else []
    sub_contents = topic.get("sub_contents", []) if isinstance(topic, dict) else []
    assessment_count_matches = (
        isinstance(topic.get("assessment_count"), int)
        and isinstance(assessments, list)
        and topic.get("assessment_count") == len(assessments)
    )

    warnings = []
    if not assessment_count_matches:
        warnings.append("assessment_count does not match topic-level assessments")
    if not isinstance(sub_contents, list) or len(sub_contents) < 4:
        warnings.append("topic has fewer than 4 sub_contents")

    return {"warnings": warnings}


def summarize_sub_content(sub_content):
    text = str(sub_content.get("content_text", "") or "")
    word_count = count_words(text)
    signals = detect_content_signals(text)

    warnings = []
    if word_count < DEFAULT_WORD_COUNT_THRESHOLD:
        warnings.append(f"content_text under {DEFAULT_WORD_COUNT_THRESHOLD} words")
    if not isinstance(sub_content.get("page_assessment"), dict):
        warnings.append("missing page_assessment")

    return {
        "word_count": word_count,
        "signals": signals,
        "warnings": warnings,
    }


def _render_badge(label, value, truthy=None):
    if truthy is None:
        truthy = bool(value)
    status = "yes" if truthy else "no"
    badge_class = "badge-yes" if truthy else "badge-no"
    display_value = escape(str(value))
    if isinstance(value, bool):
        display_value = status
    return f'<span class="badge {badge_class}">{escape(label)}: {display_value}</span>'


def _render_warning_list(warnings):
    if not warnings:
        return ""
    items = "".join(f"<li>{escape(warning)}</li>" for warning in warnings)
    return f'<div class="warning-box"><strong>Warnings</strong><ul>{items}</ul></div>'


def _render_inline_markdown(text):
    safe = escape(str(text or ""))
    safe = re.sub(r"`([^`]+)`", lambda match: f"<code>{match.group(1)}</code>", safe)
    safe = re.sub(r"\*\*([^*]+)\*\*", lambda match: f"<strong>{match.group(1)}</strong>", safe)
    safe = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", lambda match: f"<em>{match.group(1)}</em>", safe)
    return safe


def _normalize_math_markdown(text):
    normalized = str(text or "")

    replacements = (
        (r"`(\s*\\\[[\s\S]*?\\\]\s*)`", r"\1"),
        (r"`(\s*\\\([\s\S]*?\\\)\s*)`", r"\1"),
        (r"`(\s*\$\$[\s\S]*?\$\$\s*)`", r"\1"),
        (r"`(\s*\$[^`\n]+\$\s*)`", r"\1"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized)

    delimiter_fixes = (
        ("\\\\[", "\\["),
        ("\\\\]", "\\]"),
        ("\\\\(", "\\("),
        ("\\\\)", "\\)"),
    )
    for source, target in delimiter_fixes:
        normalized = normalized.replace(source, target)

    return normalized


def _split_table_row(line):
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_separator(line):
    cells = _split_table_row(line)
    if not cells:
        return False
    for cell in cells:
        compact = cell.replace(" ", "")
        if not compact or not re.fullmatch(r":?-{3,}:?", compact):
            return False
    return True


def _render_table(lines):
    header_cells = _split_table_row(lines[0])
    separator_cells = _split_table_row(lines[1])
    data_rows = [_split_table_row(line) for line in lines[2:]]

    alignments = []
    for cell in separator_cells:
        compact = cell.replace(" ", "")
        if compact.startswith(":") and compact.endswith(":"):
            alignments.append("center")
        elif compact.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")

    header_html = "".join(
        f'<th style="text-align:{alignments[index] if index < len(alignments) else "left"}">{_render_inline_markdown(cell)}</th>'
        for index, cell in enumerate(header_cells)
    )
    body_html = []
    for row in data_rows:
        row_html = "".join(
            f'<td style="text-align:{alignments[index] if index < len(alignments) else "left"}">{_render_inline_markdown(cell)}</td>'
            for index, cell in enumerate(row)
        )
        body_html.append(f"<tr>{row_html}</tr>")

    return (
        '<div class="table-wrap"><table class="markdown-table">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_html)}</tbody>"
        "</table></div>"
    )


def _render_code_block(language, code):
    language_class = ""
    if language:
        language_class = f' class="language-{escape(language)}"'
    return (
        '<pre class="code-block"><code'
        f"{language_class}>"
        f"{escape(code)}"
        "</code></pre>"
    )


def _render_markdown_content(text):
    raw_text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    code_blocks = []

    def store_code_block(match):
        language = (match.group(1) or "").strip()
        code = match.group(2).strip("\n")
        placeholder = f"@@CODEBLOCK{len(code_blocks)}@@"
        code_blocks.append((placeholder, _render_code_block(language, code)))
        return placeholder

    raw_text = re.sub(r"```([^\n`]*)\n(.*?)```", store_code_block, raw_text, flags=re.DOTALL)
    raw_text = _normalize_math_markdown(raw_text)
    lines = raw_text.split("\n")
    blocks = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        code_match = re.fullmatch(r"@@CODEBLOCK(\d+)@@", stripped)
        if code_match:
            code_index = int(code_match.group(1))
            blocks.append(code_blocks[code_index][1])
            index += 1
            continue

        if line.count("|") >= 2 and index + 1 < len(lines) and _is_table_separator(lines[index + 1]):
            table_lines = [line, lines[index + 1]]
            index += 2
            while index < len(lines):
                next_line = lines[index]
                next_stripped = next_line.strip()
                if not next_stripped or next_line.count("|") < 2:
                    break
                table_lines.append(next_line)
                index += 1
            blocks.append(_render_table(table_lines))
            continue

        unordered_match = re.match(r"^\s*[*-]\s+(.+)$", line)
        if unordered_match:
            items = []
            while index < len(lines):
                next_match = re.match(r"^\s*[*-]\s+(.+)$", lines[index])
                if not next_match:
                    break
                items.append(f"<li>{_render_inline_markdown(next_match.group(1).strip())}</li>")
                index += 1
            blocks.append(f"<ul>{''.join(items)}</ul>")
            continue

        ordered_match = re.match(r"^\s*\d+\.\s+(.+)$", line)
        if ordered_match:
            items = []
            while index < len(lines):
                next_match = re.match(r"^\s*\d+\.\s+(.+)$", lines[index])
                if not next_match:
                    break
                items.append(f"<li>{_render_inline_markdown(next_match.group(1).strip())}</li>")
                index += 1
            blocks.append(f"<ol>{''.join(items)}</ol>")
            continue

        paragraph_lines = [line.strip()]
        index += 1
        while index < len(lines):
            next_line = lines[index]
            next_stripped = next_line.strip()
            if not next_stripped:
                break
            if re.fullmatch(r"@@CODEBLOCK(\d+)@@", next_stripped):
                break
            if re.match(r"^\s*[*-]\s+(.+)$", next_line) or re.match(r"^\s*\d+\.\s+(.+)$", next_line):
                break
            if next_line.count("|") >= 2 and index + 1 < len(lines) and _is_table_separator(lines[index + 1]):
                break
            paragraph_lines.append(next_line.strip())
            index += 1

        paragraph = " ".join(paragraph_lines)
        blocks.append(f"<p>{_render_inline_markdown(paragraph)}</p>")

    return f'<div class="text-block rendered-markdown">{"".join(blocks)}</div>'


def _render_text_block(text):
    return _render_markdown_content(text)


def _render_list(items):
    if not isinstance(items, list) or not items:
        return '<div class="muted">None</div>'
    rendered = "".join(f"<li>{escape(str(item))}</li>" for item in items)
    return f"<ul>{rendered}</ul>"


def _render_assessment(assessment):
    if not isinstance(assessment, dict):
        return '<div class="muted">No page_assessment available.</div>'

    parts = [
        f"<p><strong>Type:</strong> {escape(str(assessment.get('assessment_type', '')))}</p>",
        f"<p><strong>Description:</strong> {escape(str(assessment.get('assessment_description', '')))}</p>",
    ]

    choices = assessment.get("choices")
    if isinstance(choices, list) and choices:
        parts.append("<p><strong>Choices:</strong></p>" + _render_list(choices))

    matching_pairs = assessment.get("matching_pairs")
    if isinstance(matching_pairs, list) and matching_pairs:
        pair_items = []
        for pair in matching_pairs:
            if not isinstance(pair, dict):
                continue
            prompt = escape(str(pair.get("prompt", "")))
            match = escape(str(pair.get("match", "")))
            pair_items.append(f"<li><strong>{prompt}</strong> -> {match}</li>")
        if pair_items:
            parts.append("<p><strong>Matching pairs:</strong></p><ul>" + "".join(pair_items) + "</ul>")

    match_options = assessment.get("match_options")
    if isinstance(match_options, list) and match_options:
        parts.append("<p><strong>Match options:</strong></p>" + _render_list(match_options))

    parts.append(
        f"<p><strong>Correct answer:</strong> {escape(str(assessment.get('correct_answer', '')))}</p>"
    )
    parts.append("<p><strong>Assessment focus:</strong></p>" + _render_list(assessment.get("assessment_focus")))

    return "".join(parts)


def _topic_anchor(topic, index):
    raw_title = str(topic.get("topic_title", f"Topic {index + 1}"))
    slug = re.sub(r"[^a-z0-9]+", "-", raw_title.lower()).strip("-")
    return slug or f"topic-{index + 1}"


def build_preview_html(payload, source_path):
    content = payload.get("content", {}) if isinstance(payload, dict) else {}
    topics = content.get("topics", []) if isinstance(content, dict) else []

    sidebar_items = []
    topic_sections = []

    for index, topic in enumerate(topics):
        if not isinstance(topic, dict):
            continue
        anchor = _topic_anchor(topic, index)
        topic_title = str(topic.get("topic_title", f"Topic {index + 1}"))
        sidebar_items.append(
            f'<a class="topic-link" href="#{escape(anchor)}">{escape(topic_title)}</a>'
        )

        topic_summary = summarize_topic(topic)
        topic_badges = "".join(
            [
                _render_badge("Hours", topic.get("estimated_hours", "")),
                _render_badge("Assessments", topic.get("assessment_count", "")),
                _render_badge(
                    "Assessment count matches",
                    summarize_topic(topic)["warnings"] == [] or "assessment_count does not match topic-level assessments" not in topic_summary["warnings"],
                    truthy="assessment_count does not match topic-level assessments" not in topic_summary["warnings"],
                ),
                _render_badge(
                    "Sub-contents >= 4",
                    isinstance(topic.get("sub_contents"), list) and len(topic.get("sub_contents", [])) >= 4,
                    truthy=isinstance(topic.get("sub_contents"), list) and len(topic.get("sub_contents", [])) >= 4,
                ),
            ]
        )

        sub_content_cards = []
        for sub_index, sub_content in enumerate(topic.get("sub_contents", [])):
            if not isinstance(sub_content, dict):
                continue

            sub_summary = summarize_sub_content(sub_content)
            signal_badges = "".join(
                [
                    _render_badge("Words", sub_summary["word_count"], truthy=True),
                    _render_badge("Formula", sub_summary["signals"]["formula"], truthy=sub_summary["signals"]["formula"]),
                    _render_badge("Code", sub_summary["signals"]["code"], truthy=sub_summary["signals"]["code"]),
                    _render_badge("Table", sub_summary["signals"]["table"], truthy=sub_summary["signals"]["table"]),
                    _render_badge("Visual", sub_summary["signals"]["visual"], truthy=sub_summary["signals"]["visual"]),
                    _render_badge("Citation/source", sub_summary["signals"]["citation"], truthy=sub_summary["signals"]["citation"]),
                ]
            )

            sub_content_cards.append(
                f"""
                <article class="sub-card">
                  <div class="sub-card-header">
                    <h3>{escape(str(sub_content.get("content_title", f"Sub-content {sub_index + 1}")))}</h3>
                    <div class="badge-row">{signal_badges}</div>
                  </div>
                  {_render_warning_list(sub_summary["warnings"])}
                  {_render_text_block(sub_content.get("content_text", ""))}
                  <section class="assessment-box">
                    <h4>Page Assessment</h4>
                    {_render_assessment(sub_content.get("page_assessment"))}
                  </section>
                </article>
                """
            )

        topic_sections.append(
            f"""
            <section class="topic-section" id="{escape(anchor)}">
              <div class="topic-header">
                <h2>{escape(topic_title)}</h2>
                <div class="badge-row">{topic_badges}</div>
              </div>
              {_render_warning_list(topic_summary["warnings"])}
              <div class="topic-description">{_render_markdown_content(topic.get("topic_description", ""))}</div>
              <details class="topic-assessment-list">
                <summary>Topic-level Assessments ({len(topic.get("assessments", [])) if isinstance(topic.get("assessments"), list) else 0})</summary>
                <div class="assessment-list">
                  {"".join(f'<div class="assessment-item">{_render_assessment(assessment)}</div>' for assessment in topic.get("assessments", []) if isinstance(assessment, dict))}
                </div>
              </details>
              <div class="sub-card-stack">
                {"".join(sub_content_cards) if sub_content_cards else '<div class="muted">No sub_contents found.</div>'}
              </div>
            </section>
            """
        )

    title = str(content.get("skill_name", "Content Test Preview"))
    description = str(content.get("description", ""))
    difficulty = str(content.get("difficulty_level", ""))
    audience = str(content.get("target_audience", ""))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(title)} Preview</title>
  <style>
    :root {{
      --bg: #f7f4ee;
      --panel: #fffdf8;
      --ink: #231d16;
      --muted: #6f6559;
      --border: #ddd2c4;
      --accent: #0f766e;
      --warn: #b45309;
      --bad: #a61b1b;
      --good-bg: #e5f7f1;
      --bad-bg: #fbeaea;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: linear-gradient(180deg, #faf7f2 0%, var(--bg) 100%);
    }}
    .layout {{
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      min-height: 100vh;
    }}
    .sidebar {{
      position: sticky;
      top: 0;
      align-self: start;
      height: 100vh;
      overflow: auto;
      padding: 20px;
      border-right: 1px solid var(--border);
      background: #f2ede4;
    }}
    .sidebar h1 {{
      margin: 0 0 8px;
      font-size: 1.1rem;
      line-height: 1.4;
    }}
    .sidebar p {{
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
    }}
    .topic-nav {{
      display: grid;
      gap: 8px;
      margin-top: 16px;
    }}
    .topic-link {{
      text-decoration: none;
      color: var(--ink);
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: rgba(255,255,255,0.75);
      font-size: 0.93rem;
      line-height: 1.4;
    }}
    .main {{
      padding: 24px;
    }}
    .hero, .topic-section, .sub-card, .assessment-item {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
    }}
    .hero {{
      padding: 20px;
      margin-bottom: 20px;
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: 1.8rem;
    }}
    .hero p {{
      line-height: 1.7;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .meta-card {{
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: #fcfaf5;
    }}
    .meta-card strong {{
      display: block;
      font-size: 0.78rem;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .topic-stack {{
      display: grid;
      gap: 18px;
    }}
    .topic-section {{
      padding: 18px;
    }}
    .topic-header {{
      display: grid;
      gap: 10px;
    }}
    .topic-header h2 {{
      margin: 0;
      font-size: 1.3rem;
    }}
    .topic-description {{
      line-height: 1.7;
      color: var(--ink);
    }}
    .badge-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 0.82rem;
      border: 1px solid var(--border);
      background: #f6f1e8;
    }}
    .badge-yes {{
      background: var(--good-bg);
    }}
    .badge-no {{
      background: var(--bad-bg);
    }}
    .warning-box {{
      margin: 14px 0;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid #f0c48a;
      background: #fff3df;
    }}
    .warning-box ul {{
      margin: 8px 0 0;
      padding-left: 18px;
    }}
    .sub-card-stack {{
      display: grid;
      gap: 14px;
      margin-top: 16px;
    }}
    .sub-card {{
      padding: 16px;
    }}
    .sub-card-header h3 {{
      margin: 0 0 10px;
      font-size: 1.08rem;
    }}
    .text-block {{
      line-height: 1.75;
      color: var(--ink);
      background: #fcfaf5;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
      overflow-wrap: anywhere;
    }}
    .rendered-markdown p {{
      margin: 0 0 1em;
    }}
    .rendered-markdown p:last-child {{
      margin-bottom: 0;
    }}
    .rendered-markdown strong {{
      font-weight: 700;
    }}
    .rendered-markdown em {{
      font-style: italic;
    }}
    .rendered-markdown ul,
    .rendered-markdown ol {{
      margin: 0 0 1em 1.4em;
      padding: 0;
      line-height: 1.75;
    }}
    .rendered-markdown li {{
      margin-bottom: 0.35em;
    }}
    .rendered-markdown code {{
      font-family: "SFMono-Regular", "Menlo", "Consolas", monospace;
      font-size: 0.93em;
      background: #efe7d9;
      border-radius: 6px;
      padding: 0.12em 0.35em;
    }}
    .code-block {{
      margin: 0 0 1em;
      padding: 14px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: #f3ede2;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .code-block code {{
      background: transparent;
      padding: 0;
      border-radius: 0;
      display: block;
      line-height: 1.65;
    }}
    .table-wrap {{
      overflow-x: auto;
      margin: 0 0 1em;
    }}
    .markdown-table {{
      width: 100%;
      border-collapse: collapse;
      background: #fffdf8;
    }}
    .markdown-table th,
    .markdown-table td {{
      border: 1px solid var(--border);
      padding: 8px 10px;
      vertical-align: top;
    }}
    .markdown-table th {{
      background: #f2ede4;
      font-weight: 700;
    }}
    .assessment-box, .topic-assessment-list {{
      margin-top: 16px;
    }}
    .assessment-box {{
      padding-top: 10px;
      border-top: 1px solid var(--border);
    }}
    .assessment-box h4 {{
      margin: 0 0 10px;
    }}
    .assessment-item {{
      padding: 14px;
      margin-top: 12px;
    }}
    .assessment-item p {{
      margin: 0 0 10px;
      line-height: 1.65;
    }}
    .assessment-item ul, .assessment-box ul {{
      margin: 0 0 10px 18px;
      line-height: 1.6;
    }}
    .muted {{
      color: var(--muted);
    }}
    details summary {{
      cursor: pointer;
      font-weight: 600;
    }}
    @media (max-width: 960px) {{
      .layout {{
        grid-template-columns: 1fr;
      }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: none;
        border-bottom: 1px solid var(--border);
      }}
    }}
  </style>
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],
        displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']]
      }},
      options: {{
        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
      }}
    }};
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h1>{escape(title)}</h1>
      <p><strong>Source:</strong> {escape(str(source_path))}</p>
      <p>{escape(description[:240] + ("..." if len(description) > 240 else ""))}</p>
      <nav class="topic-nav">
        {"".join(sidebar_items) if sidebar_items else '<span class="muted">No topics found.</span>'}
      </nav>
    </aside>
    <main class="main">
      <section class="hero">
        <h1>{escape(title)}</h1>
        <p>{escape(description)}</p>
        <div class="meta-grid">
          <div class="meta-card"><strong>Difficulty</strong>{escape(difficulty)}</div>
          <div class="meta-card"><strong>Target Audience</strong>{escape(audience)}</div>
          <div class="meta-card"><strong>Topics</strong>{len(topics) if isinstance(topics, list) else 0}</div>
          <div class="meta-card"><strong>Source File</strong>{escape(Path(source_path).name)}</div>
        </div>
      </section>
      <div class="topic-stack">
        {"".join(topic_sections) if topic_sections else '<div class="muted">No content topics found.</div>'}
      </div>
    </main>
  </div>
  <script>
    window.addEventListener("load", function () {{
      if (window.MathJax && window.MathJax.typesetPromise) {{
        window.MathJax.typesetPromise();
      }}
    }});
  </script>
</body>
</html>
"""


def build_output_path(input_path, output_path=None):
    if output_path is not None:
        return Path(output_path)
    input_path = Path(input_path)
    return input_path.with_name(f"{input_path.stem}_preview.html")


def generate_preview(input_path, output_path=None):
    input_path = Path(input_path)
    payload = load_content_test_json(input_path)
    html = build_preview_html(payload, input_path)
    output_path = build_output_path(input_path, output_path=output_path)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a lightweight local HTML preview for a content-test JSON file."
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--input",
        dest="input_option",
        help="Path to a content-test JSON file.",
    )
    parser.add_argument(
        "--output",
        help="Optional output HTML path.",
    )
    args = parser.parse_args(argv)

    input_path = args.input_option or args.input_path
    if not input_path:
        print("An input JSON path is required.", file=sys.stderr)
        return 1

    try:
        output_path = generate_preview(input_path, output_path=args.output)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(str(output_path), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
