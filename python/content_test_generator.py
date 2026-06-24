import argparse
import json
import sys
from pathlib import Path

from syllabus_service import (
    CONTENT_TEST_OUTPUT_DIR,
    DEFAULT_CONTENT_TEST_INPUT_PATH,
    load_payload,
    run_content_test,
    summarize_content_test_output,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the original content-generation test pipeline and save parsed outputs."
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--input",
        dest="input_option",
        help="Path to a JSON input payload.",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Model name to use for generation.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(CONTENT_TEST_OUTPUT_DIR),
        help="Directory where parsed content-test outputs are saved.",
    )
    parser.add_argument(
        "--save-only",
        action="store_true",
        help="Save the parsed JSON without printing it to stdout.",
    )
    args = parser.parse_args(argv)

    input_path = args.input_option or args.input_path or str(DEFAULT_CONTENT_TEST_INPUT_PATH)
    payload = load_payload(Path(input_path))

    try:
        result = run_content_test(
            payload,
            model_name=args.model,
            output_dir=Path(args.output_dir),
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    summary = summarize_content_test_output(result["parsed_output"])
    print(f"saved_path: {result['saved_path']}", file=sys.stderr)
    print(f"topics: {summary['topic_count']}", file=sys.stderr)
    print(f"total_sub_contents: {summary['total_sub_contents']}", file=sys.stderr)
    print(
        f"every_sub_content_has_page_assessment: {summary['every_sub_content_has_page_assessment']}",
        file=sys.stderr,
    )
    print(
        f"minimum_content_text_word_count: {summary['minimum_content_text_word_count']}",
        file=sys.stderr,
    )
    print(
        f"assessment_count_matches: {summary['assessment_count_matches']}",
        file=sys.stderr,
    )
    if not args.save_only:
        print(json.dumps(result["parsed_output"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
