#!/usr/bin/env python3
"""Standalone direct prompt-provider transport checks."""

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]

folder_paths = types.ModuleType("folder_paths")
folder_paths.root = str(ROOT)
folder_paths.get_output_directory = lambda: folder_paths.root
folder_paths.get_temp_directory = lambda: folder_paths.root
folder_paths.get_input_directory = lambda: folder_paths.root
sys.modules["folder_paths"] = folder_paths

spec = importlib.util.spec_from_file_location(
    "h3_prompt_optimizer_unit", ROOT / "prompt_optimizer.py")
optimizer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = optimizer
spec.loader.exec_module(optimizer)


def rejected(function, *args):
    try:
        function(*args)
    except ValueError as exc:
        return str(exc)
    raise AssertionError("Expected ValueError")


assert "not allowed" in rejected(
    optimizer.optimizer_url,
    "http://127.0.0.1:1234/v1", "openai", "model")
assert "not allowed" in rejected(
    optimizer._validate_api_destination, "http://169.254.169.254/latest/meta-data")
assert "not allowed" in rejected(
    optimizer._AllowedRedirectHandler().redirect_request,
    None, None, 302, "Found", {},
    "http://169.254.169.254/latest/meta-data")
assert "original origin" in rejected(
    optimizer._AllowedRedirectHandler().redirect_request,
    types.SimpleNamespace(full_url="https://api.openai.com/v1/responses"),
    None, 307, "Temporary Redirect", {},
    "https://openrouter.ai/api/v1/responses")
assert "credentials" in rejected(
    optimizer._validate_api_destination,
    "https://user:secret@api.openai.com/v1")
assert optimizer.optimizer_url(
    "https://api.openai.com/v1/responses", "responses", "model") == \
    "https://api.openai.com/v1/responses"
assert optimizer.optimizer_url(
    "https://generativelanguage.googleapis.com", "gemini",
    "models/gemini-test") == \
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
os.environ[optimizer.ALLOWED_ORIGINS_ENV] = (
    "https://api.example,http://127.0.0.1:1234")
assert optimizer.optimizer_url(
    "https://api.example/v1", "openai", "model") == \
    "https://api.example/v1/chat/completions"
assert optimizer.optimizer_url(
    "https://api.example/custom/chat/completions", "openai", "model") == \
    "https://api.example/custom/chat/completions"
assert optimizer._clean_result("```text\nA complete prompt.\n```") == \
    "A complete prompt."
assert optimizer._clean_result(json.dumps({
    "rewritten_prompt": "A structured replacement.",
})) == "A structured replacement."


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return json.dumps(self.payload).encode("utf-8")


requests = []


def fake_urlopen(request, timeout):
    requests.append((request, timeout))
    return FakeResponse({
        "choices": [{"message": {"content": "Rewritten H3 prompt."}}],
    })


optimizer._open_direct_api_request = fake_urlopen
result = optimizer.call_direct_optimizer(
    "http://127.0.0.1:1234/v1", "", "local-model", "openai",
    "Rewrite this scene.")
assert result == "Rewritten H3 prompt."
request, timeout = requests[-1]
assert request.full_url == "http://127.0.0.1:1234/v1/chat/completions"
assert timeout == optimizer.REQUEST_TIMEOUT_SECONDS
payload = json.loads(request.data)
assert payload["model"] == "local-model"
assert payload["messages"][0]["role"] == "system"
os.environ.pop(optimizer.ALLOWED_ORIGINS_ENV, None)

with tempfile.TemporaryDirectory() as temporary:
    folder_paths.root = temporary
    image = pathlib.Path(temporary) / "refs" / "hero.png"
    image.parent.mkdir()
    image.write_bytes(b"image bytes")
    resources = [{
        "type": "image",
        "tag": "@hero",
        "asset": {
            "filename": "hero.png",
            "subfolder": "refs",
            "storage": "input",
        },
    }]
    parts = optimizer._media_parts(resources, "openai")
    assert len(parts) == 2
    assert "@hero" in parts[0]["text"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert optimizer._asset_path({
        "filename": "outside.png", "subfolder": "../", "storage": "input",
    }) is None

print("H3 Direct prompt optimizer: URL, response, and safe media handling pass")
