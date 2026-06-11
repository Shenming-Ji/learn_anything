import sys
import json
from pathlib import Path
from syllabus_service import DEFAULT_INPUT_PATH, generate_syllabus, load_payload


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    input_path = Path(argv[0]) if argv else DEFAULT_INPUT_PATH
    payload = load_payload(input_path)
    print(f"Generating syllabus from {input_path}...", file=sys.stderr)
    output = generate_syllabus(payload)

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
