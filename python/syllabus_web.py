import argparse
import json
import threading
import uuid
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from syllabus_service import (
    DEFAULT_INPUT_PATH,
    add_images,
    add_sub_contents,
    build_outline_preview,
    build_client,
    call_coach,
    generate_course_details,
    generate_content_plan,
    generate_syllabus,
    generate_syllabus_outline,
    load_payload,
    merge_generated_sections,
)


BASE_DIR = Path(__file__).resolve().parents[1]
HTML_PATH = Path(__file__).with_name("syllabus_web.html")
SAMPLE_INPUTS = {
    "space": DEFAULT_INPUT_PATH,
    "ds_health": Path(__file__).with_name("inputs") / "ds_health.json",
}
TASKS = {}
TASKS_LOCK = threading.Lock()


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
        "personal_parameters": [],
    }


def load_sample_payload(sample_name):
    if sample_name not in SAMPLE_INPUTS:
        raise KeyError(f"Unknown sample: {sample_name}")
    return load_payload(SAMPLE_INPUTS[sample_name])


def _create_task(kind, initial_message):
    task_id = uuid.uuid4().hex
    task = {
        "task_id": task_id,
        "kind": kind,
        "state": "queued",
        "progress": 0,
        "message": initial_message,
        "error": None,
        "result": None,
    }
    with TASKS_LOCK:
        TASKS[task_id] = task
    return deepcopy(task)


def _update_task(task_id, **updates):
    with TASKS_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return None
        task.update(updates)
        return deepcopy(task)


def _get_task(task_id):
    with TASKS_LOCK:
        task = TASKS.get(task_id)
        return deepcopy(task) if task is not None else None


def _run_outline_task(task_id, payload, outline_feedback="", regenerate=False):
    try:
        _update_task(
            task_id,
            state="running",
            progress=10,
            message="Started outline generation.",
        )
        syllabus = generate_syllabus_outline(
            payload,
            outline_feedback=outline_feedback,
            regenerate=regenerate,
        )
        _update_task(
            task_id,
            state="running",
            progress=35,
            message="Outline generated. Preparing preview...",
        )
        output = build_outline_preview(payload, syllabus)
        _update_task(
            task_id,
            state="completed",
            progress=100,
            message="Outline ready.",
            result={"payload": payload, "syllabus": syllabus, "output": output},
        )
    except Exception as exc:  # pragma: no cover
        _update_task(
            task_id,
            state="error",
            progress=100,
            message=f"Outline generation failed: {exc}",
            error=str(exc),
        )


def _run_details_task(task_id, payload, syllabus):
    try:
        client = build_client()
        _update_task(
            task_id,
            state="running",
            progress=50,
            message="Generating content plan...",
        )
        content = generate_content_plan(payload, syllabus, client=client)
        output = merge_generated_sections(payload, syllabus, content)
        _update_task(
            task_id,
            state="running",
            progress=75,
            message="Generating contents...",
        )
        output = add_sub_contents(output, client=client)
        _update_task(
            task_id,
            state="running",
            progress=90,
            message="Fetching images...",
        )
        output = add_images(output)
        _update_task(
            task_id,
            state="completed",
            progress=100,
            message="Full course generation complete.",
            result={"payload": payload, "syllabus": syllabus, "output": output},
        )
    except Exception as exc:  # pragma: no cover
        _update_task(
            task_id,
            state="error",
            progress=100,
            message=f"Full course generation failed: {exc}",
            error=str(exc),
        )


def start_outline_task(payload, outline_feedback="", regenerate=False):
    task = _create_task("outline", "Queued outline generation...")
    thread = threading.Thread(
        target=_run_outline_task,
        args=(task["task_id"], payload, outline_feedback, regenerate),
        daemon=True,
    )
    thread.start()
    return task


def start_details_task(payload, syllabus):
    task = _create_task("details", "Queued full course generation...")
    thread = threading.Thread(target=_run_details_task, args=(task["task_id"], payload, syllabus), daemon=True)
    thread.start()
    return task


class SyllabusWebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self._serve_html()
            return

        if parsed.path == "/api/sample":
            self._serve_sample(parsed.query)
            return

        if parsed.path.startswith("/api/tasks/"):
            self._serve_task_status(parsed.path)
            return

        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/generate-outline":
            self._generate_outline()
            return

        if parsed.path == "/api/generate-outline-async":
            self._start_outline_task()
            return

        if parsed.path == "/api/generate-details":
            self._generate_details()
            return

        if parsed.path == "/api/generate-details-async":
            self._start_details_task()
            return

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

    def _serve_task_status(self, path):
        task_id = path.rsplit("/", 1)[-1].strip()
        task = _get_task(task_id)
        if task is None:
            self._send_json({"error": f"Unknown task '{task_id}'."}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json(task)

    def _generate_syllabus(self):
        request_data = self._read_json_body()
        if request_data is None:
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

    def _start_outline_task(self):
        request_data = self._read_json_body()
        if request_data is None:
            return

        try:
            payload = build_payload_from_form(request_data)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        outline_feedback = str(request_data.get("outline_feedback", "")).strip()
        regenerate = bool(request_data.get("regenerate_outline"))
        task = start_outline_task(payload, outline_feedback=outline_feedback, regenerate=regenerate)
        self._send_json(task, status=HTTPStatus.ACCEPTED)

    def _generate_outline(self):
        request_data = self._read_json_body()
        if request_data is None:
            return

        try:
            payload = build_payload_from_form(request_data)
            syllabus = generate_syllabus_outline(
                payload,
                outline_feedback=str(request_data.get("outline_feedback", "")).strip(),
                regenerate=bool(request_data.get("regenerate_outline")),
            )
            output = build_outline_preview(payload, syllabus)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:  # pragma: no cover
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json({"payload": payload, "syllabus": syllabus, "output": output})

    def _start_details_task(self):
        request_data = self._read_json_body()
        if request_data is None:
            return

        try:
            payload = build_payload_from_form(request_data.get("payload", {}))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        syllabus = request_data.get("syllabus")
        if not isinstance(syllabus, dict) or not syllabus:
            self._send_json({"error": "syllabus is required."}, status=HTTPStatus.BAD_REQUEST)
            return

        task = start_details_task(payload, syllabus)
        self._send_json(task, status=HTTPStatus.ACCEPTED)

    def _generate_details(self):
        request_data = self._read_json_body()
        if request_data is None:
            return

        try:
            payload = build_payload_from_form(request_data.get("payload", {}))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        syllabus = request_data.get("syllabus")
        if not isinstance(syllabus, dict) or not syllabus:
            self._send_json({"error": "syllabus is required."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            output = generate_course_details(payload, syllabus)
        except Exception as exc:  # pragma: no cover
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json({"payload": payload, "syllabus": syllabus, "output": output})

    def _read_json_body(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length header."}, status=HTTPStatus.BAD_REQUEST)
            return None

        try:
            raw_body = self.rfile.read(content_length).decode("utf-8")
            return json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            self._send_json({"error": "Request body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
            return None

    def _handle_coach(self):
        request_data = self._read_json_body()
        if request_data is None:
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
