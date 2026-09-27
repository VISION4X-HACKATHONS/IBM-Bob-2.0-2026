from __future__ import annotations

import difflib
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from backend.storage import get_analysis

OLLAMA_DEFAULT_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_DEFAULT_MODEL = "qwen2.5-coder:7b"
GEMINI_DEFAULT_MODEL = "gemini-3.7-flash"


def _llm_provider() -> str:
    return os.getenv("LLM_PROVIDER", "ollama").strip().lower()


def _ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", OLLAMA_DEFAULT_BASE_URL)


def _ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)


def _gemini_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "").strip()


def _gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL).strip()


def _call_ollama(payload: dict[str, Any]) -> str:
    base_url = _ollama_base_url().rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        chunks: list[str] = []
        for raw in response:
            if not raw:
                continue
            chunk = json.loads(raw.decode("utf-8"))
            text = chunk.get("response", "")
            if text:
                chunks.append(text)
        return "".join(chunks)


def _call_gemini(prompt: str) -> str:
    api_key = _gemini_api_key()
    if not api_key:
        raise RuntimeError("Gemini API key is not configured. Set GEMINI_API_KEY before selecting the Gemini provider.")
    model = _gemini_model()
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if "error" in payload:
        message = payload["error"].get("message", "Gemini request failed.")
        raise RuntimeError(message)
    candidates = payload.get("candidates", [])
    chunks: list[str] = []
    for candidate in candidates:
        for part in candidate.get("content", {}).get("parts", []):
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if not chunks:
        raise ValueError("Gemini response did not include any generated content.")
    return "".join(chunks)


def _call_llm(prompt: str) -> str:
    provider = _llm_provider()
    if provider == "gemini":
        return _call_gemini(prompt)
    if provider == "ollama":
        return _call_ollama({"model": _ollama_model(), "prompt": prompt, "stream": False})
    raise RuntimeError(f"Unsupported LLM provider: {provider}")


def _load_plan_context(plan_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    item = get_analysis(plan_id)
    if item is None:
        raise ValueError(f"Plan {plan_id} not found.")
    result = item.get("result", {})
    plan = result.get("plan", [])
    repository_path = item.get("repository_path") or result.get("repository_path")
    if not repository_path:
        raise ValueError("Analysis record is missing the repository path.")
    if not plan:
        raise ValueError("Implementation plan is empty.")
    return item, {"repository_path": repository_path, "result": result, "plan": plan}


def _extract_allowed_files(plan: dict[str, Any]) -> set[str]:
    files: set[str] = set()
    for task in plan.get("plan", []):
        for file in task.get("files", []):
            if isinstance(file, str):
                files.add(file)
    return {str(path).replace("\\", "/") for path in files}


def _normalize_rel_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../") or normalized == "..":
        raise ValueError(f"Generated file path must stay inside the approved allowlist: {path}")
    if ".." in Path(normalized).parts:
        raise ValueError(f"Generated file path must stay inside the approved allowlist: {path}")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _validate_generated_files(allowed_files: set[str], generated: Any) -> list[dict[str, str]]:
    if not isinstance(generated, dict):
        raise ValueError("Model output must be a JSON object.")
    files = generated.get("files")
    if not isinstance(files, list):
        raise ValueError("Model output must include a JSON 'files' array.")
    validated: list[dict[str, str]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("Each file entry must be an object.")
        file_name = entry.get("file")
        content = entry.get("content")
        if not isinstance(file_name, str) or not isinstance(content, str):
            raise ValueError("Each generated file must have string file and content values.")
        normalized = _normalize_rel_path(file_name)
        if normalized not in allowed_files:
            raise ValueError(f"Generated file outside approved allowlist: {normalized}")
        if not content.strip():
            raise ValueError(f"Generated file content is empty: {normalized}")
        validated.append({"file": normalized, "content": content})
    if not validated:
        raise ValueError("No valid generated files were returned.")
    if len(validated) > max(10, len(allowed_files) * 2):
        raise ValueError("Generated file count is not reasonable for this change.")
    return validated


def _build_prompt(item: dict[str, Any], plan: dict[str, Any], repository_path: str) -> str:
    request = item.get("result", {}).get("request", "")
    allowed_files = sorted(_extract_allowed_files(plan))
    repository = Path(repository_path)
    file_context = []
    for relative_path in allowed_files:
        full_path = repository / relative_path
        if full_path.exists() and full_path.is_file():
            file_context.append(f"FILE: {relative_path}\n```\n{full_path.read_text(encoding='utf-8', errors='ignore')}\n```\n")
    root_manifest = ["requirements.txt", "package.json", "pyproject.toml"]
    for name in root_manifest:
        candidate = repository / name
        if candidate.exists():
            file_context.append(f"FILE: {name}\n```\n{candidate.read_text(encoding='utf-8', errors='ignore')}\n```\n")
    relevant_tests = []
    for candidate in sorted(repository.rglob("*")):
        if candidate.is_file() and re.search(r"(?:^test_.*\.py$|.*_test\.py$|.*\.(test|spec)\.[jt]sx?$)", candidate.name, re.IGNORECASE):
            relevant_tests.append(candidate)
    for test_file in relevant_tests[:8]:
        rel = test_file.relative_to(repository).as_posix()
        if rel not in allowed_files:
            file_context.append(f"TEST_FILE: {rel}\n```\n{test_file.read_text(encoding='utf-8', errors='ignore')}\n```\n")
    prompt = (
        "You are operating on an existing production-style repository.\n"
        "Modify only the files in the approved allowlist.\n"
        "Preserve existing functionality and repository conventions.\n"
        "Do not invent APIs that do not exist.\n"
        "Do not expose secrets.\n"
        "Do not modify unrelated files.\n"
        "Return only valid JSON matching this schema:\n"
        "{\n"
        "  \"files\": [\n"
        "    {\"file\": \"relative/path.py\", \"content\": \"complete new file contents\"}\n"
        "  ],\n"
        "  \"summary\": \"short explanation\"\n"
        "}\n"
        f"The change request is:\n{request}\n\n"
        "Approved files:\n"
        f"{chr(10).join(allowed_files)}\n\n"
        "Repository context:\n"
        f"{chr(10).join(file_context)}\n\n"
        "Rules:\n"
        "- Only include files that actually need modification.\n"
        "- If a file does not need change, do not return it.\n"
        "- Use complete replacement content for each changed file.\n"
        "- No markdown fences, no prose outside JSON.\n"
        "- No absolute paths or parent traversal.\n"
    )
    return prompt


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _repair_json_string_literals(raw: str) -> str:
    def _escape_value(match: re.Match[str]) -> str:
        literal = match.group(0)
        return literal.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")

    return re.sub(r'"(?:\\.|[^"\\])*"', _escape_value, raw)


def _parse_model_json(raw: str) -> dict[str, Any]:
    cleaned = _strip_fences(raw)
    repaired = _repair_json_string_literals(cleaned)
    try:
        data = json.loads(repaired)
    except json.JSONDecodeError as exc:
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            raise ValueError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Model JSON must be an object.")
    if "files" not in data:
        raise ValueError("Model JSON must contain a 'files' field.")
    return data


def _build_patch_data(repository_path: str, generated_files: list[dict[str, str]]) -> list[dict[str, str]]:
    repo_root = Path(repository_path)
    patch_data: list[dict[str, str]] = []
    for entry in generated_files:
        relative_path = entry["file"]
        target = repo_root / relative_path
        original = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else ""
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                entry["content"].splitlines(keepends=True),
                fromfile="/dev/null" if not target.exists() else relative_path,
                tofile=relative_path,
                lineterm="",
            )
        )
        if not diff:
            raise ValueError(f"No diff generated for {relative_path}")
        patch_data.append({"file": relative_path, "unified_diff": diff})
    return patch_data


def generate_code_patches(plan_id: str) -> dict[str, Any]:
    try:
        _call_llm("ping")
    except Exception as exc:  # pragma: no cover - surfaced to API
        provider = _llm_provider()
        if provider == "ollama":
            raise RuntimeError("AI code generator unavailable. Start Ollama and ensure the configured model exists.") from exc
        raise RuntimeError(f"AI code generator unavailable for provider '{provider}'. Check the provider configuration and credentials.") from exc

    item, plan_context = _load_plan_context(plan_id)
    repository_path = plan_context["repository_path"]
    allowed_files = _extract_allowed_files(plan_context)
    prompt = _build_prompt(item, plan_context, repository_path)
    try:
        response_text = _call_llm(prompt)
    except Exception as exc:  # pragma: no cover - surfaced to API
        provider = _llm_provider()
        if provider == "ollama":
            raise RuntimeError("AI code generator unavailable. Start Ollama and ensure the configured model exists.") from exc
        raise RuntimeError(f"AI code generator unavailable for provider '{provider}'. Check the provider configuration and credentials.") from exc
    payload = _parse_model_json(response_text)
    generated_files = _validate_generated_files(allowed_files, payload)
    patch_data = _build_patch_data(repository_path, generated_files)
    return {"files": generated_files, "patch_data": patch_data, "summary": str(payload.get("summary", "Generated code changes."))}
