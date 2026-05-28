import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from syllabus_service import DEFAULT_INPUT_PATH, call_coach, generate_syllabus, load_payload


BASE_DIR = Path(__file__).resolve().parents[1]
HTML_PATH = Path(__file__).with_name("syllabus_web.html")
SAMPLE_INPUTS = {
    "space": DEFAULT_INPUT_PATH,
    "ds_health": Path(__file__).with_name("inputs") / "ds_health.json",
}


def split_personal_parameters(raw_value):
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]

    if raw_value is None:
        return []

    text = str(raw_value).replace("\r", "\n")
    items = []
    for line in text.split("\n"):
        parts = [part.strip() for part in line.split(",")]
        items.extend(part for part in parts if part)
    return items


def build_payload_from_form(form_data):
    target_skill = str(form_data.get("target_skill", "")).strip()
    if not target_skill:
        raise ValueError("target_skill is required.")

    def read_int(field_name):
        raw_value = form_data.get(field_name)
        if raw_value in (None, ""):
            raise ValueError(f"{field_name} is required.")
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an integer.") from exc
        if value <= 0:
            raise ValueError(f"{field_name} must be greater than 0.")
        return value

    return {
        "target_skill": target_skill,
        "duration_weeks": read_int("duration_weeks"),
        "difficulty_level": read_int("difficulty_level"),
        "learning_style": str(form_data.get("learning_style", "practical")).strip() or "practical",
        "hours_per_week": read_int("hours_per_week"),
        "personal_parameters": split_personal_parameters(form_data.get("personal_parameters")),
    }


def load_sample_payload(sample_name):
    if sample_name not in SAMPLE_INPUTS:
        raise KeyError(f"Unknown sample: {sample_name}")
    return load_payload(SAMPLE_INPUTS[sample_name])


class SyllabusWebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self._serve_html()
            return

        if parsed.path == "/api/sample":
            self._serve_sample(parsed.query)
            return

        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/generate":
            self._generate_syllabus()
            return

        if parsed.path == "/coach":
            self._handle_coach()
            return

        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format, *args):
        return

    def _serve_html(self):
        html = HTML_PATH.read_text(encoding="utf-8")
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sample(self, query_string):
        params = parse_qs(query_string)
        sample_name = params.get("name", ["space"])[0]

        try:
            payload = load_sample_payload(sample_name)
        except KeyError:
            self._send_json({"error": f"Unknown sample '{sample_name}'."}, status=HTTPStatus.NOT_FOUND)
            return

        self._send_json({"payload": payload})

    def _generate_syllabus(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length header."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            raw_body = self.rfile.read(content_length).decode("utf-8")
            request_data = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            self._send_json({"error": "Request body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            payload = build_payload_from_form(request_data)
            output = generate_syllabus(payload)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:  # pragma: no cover
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json({"payload": payload, "output": output})

    def _handle_coach(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length header."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            raw_body = self.rfile.read(content_length).decode("utf-8")
            request_data = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            self._send_json({"error": "Request body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
            return

        message = str(request_data.get("message", "")).strip()
        if not message:
            self._send_json({"error": "message is required."}, status=HTTPStatus.BAD_REQUEST)
            return

        course = request_data.get("course") or {}

        try:
            reply = call_coach(course, message)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json({"reply": reply})

    def _send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the syllabus generator web interface.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the local web server.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind the local web server.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), SyllabusWebHandler)
    print(f"Syllabus web UI running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
