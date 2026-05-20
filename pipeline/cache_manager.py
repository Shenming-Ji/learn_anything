import hashlib
import json
from pathlib import Path


DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache"


def ensure_cache_dir(cache_dir):
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path


def normalize_input(input_data):
    if isinstance(input_data, dict):
        return {
            key: normalize_input(value)
            for key, value in sorted(input_data.items())
        }

    if isinstance(input_data, (list, tuple)):
        return [normalize_input(item) for item in input_data]

    if isinstance(input_data, str):
        return " ".join(input_data.split())

    return input_data


def make_cache_key(skill_name, skill_version, input_data):
    normalized_input = normalize_input(input_data)
    cache_payload = {
        "skill_name": skill_name,
        "skill_version": skill_version,
        "input_data": normalized_input,
    }
    serialized_payload = json.dumps(
        cache_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()


def get_cached_output(cache_key, cache_dir=DEFAULT_CACHE_DIR):
    cache_file = ensure_cache_dir(cache_dir) / f"{cache_key}.json"
    if not cache_file.exists():
        return None

    try:
        with open(cache_file, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return None


def save_cached_output(cache_key, output_data, cache_dir=DEFAULT_CACHE_DIR):
    cache_file = ensure_cache_dir(cache_dir) / f"{cache_key}.json"
    with open(cache_file, "w", encoding="utf-8") as file:
        json.dump(output_data, file, indent=2, sort_keys=True, ensure_ascii=False)
        file.write("\n")
