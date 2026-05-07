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
- `python/inputs/health.json`

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
