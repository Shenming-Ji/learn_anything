# Learn Anything

This project contains two separate Python scripts:

- `python/chatbot.py`
  Builds a simple document-based chatbot. It reads course files, creates a FAISS vector database, and answers questions using retrieved context.
- `python/syllabus_generator.py`
  Generates a course syllabus from a JSON input file using Gemini on Vertex AI.

## Project Structure

- `docs/`: sample course materials
- `python/`: main Python scripts
- `scripts/`: helper script and requirements file
- `tests/`: unit tests for `syllabus_generator.py`

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r scripts/requirements.txt
```

## Run The Syllabus Generator

Default example input:

```bash
python3 python/syllabus_generator.py
```

Custom input file:

```bash
python3 python/syllabus_generator.py path/to/input.json
```

Example input file:

- `python/inputs/space.json`
- `python/inputs/ds_health.json`

## Run The Web Interface

Start the local interface:

```bash
python3 python/syllabus_web.py
```

Then open:

```text
http://127.0.0.1:8000
```

Optional host and port:

```bash
python3 python/syllabus_web.py --host 0.0.0.0 --port 9000
```

The web UI lets users enter `target_skill`, `duration_weeks`, `difficulty_level`, `learning_style`, `hours_per_week`, and `personal_parameters`, previews the generated input JSON, and shows the final output as both readable sections and pretty JSON.

## Run The Unit Test

```bash
python3 -m unittest tests/test_syllabus_generator.py
```

This test does not call the real Gemini API.

## Run The Chatbot

The chatbot expects:

- a document directory from `-d`
- a vector database directory from `-db`
- optional `-b` to build the vector database first

Example:

```bash
cd python
python3 chatbot.py -d ../docs -db ../vectordb -b
```

Supported document types:

- `.pdf`
- `.txt`
- `.docx`
