"""
Phase 2 – LLM Engine: LLM API client.

Wraps the OpenAI and Anthropic APIs with:
  - A configurable temperature.
  - An artificial pause of ≥13 seconds between calls to respect rate limits.
  - Support for binary and non-binary classification modes.
  - Exponential backoff retry logic (up to 3 retries: 2/4/8 seconds).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import time
import logging
import threading
from typing import Any, Callable, Optional

from config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    DEEPSEEK_REASONING_EFFORT,
    DEEPSEEK_THINKING_ENABLED,
    ANTHROPIC_API_KEY,
    GITHUB_TOKEN,
    DEFAULT_MODEL,
    GITHUB_FALLBACK_MODEL,
    TEMPERATURE,
    LLM_MAX_TOKENS,
    API_PAUSE_SECONDS,
    LLM_TRACE_MESSAGES,
    LLM_TRACE_MAX_CHARS,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2  # seconds (doubles each retry: 2, 4, 8)

# ---------------------------------------------------------------------------
# Lazy imports – only import what the user actually needs, cached per process
# ---------------------------------------------------------------------------

_openai_client = None
_anthropic_client = None
_github_client = None

_LLM_TELEMETRY_COLLECTOR: ContextVar[Optional[Callable[[dict[str, Any]], None]]] = ContextVar(
    "llm_telemetry_collector",
    default=None,
)
_LLM_PROCESS: ContextVar[str] = ContextVar("llm_process", default="unspecified")
_LLM_SHUTDOWN_REQUESTED = threading.Event()


def request_llm_shutdown() -> None:
    """Signal that no new LLM calls should start (used during app shutdown)."""
    _LLM_SHUTDOWN_REQUESTED.set()


def clear_llm_shutdown() -> None:
    """Clear shutdown signal (used when app starts/restarts)."""
    _LLM_SHUTDOWN_REQUESTED.clear()


def _raise_if_shutdown_requested() -> None:
    if _LLM_SHUTDOWN_REQUESTED.is_set():
        raise RuntimeError("LLM client is shutting down; rejecting new requests")


def _sleep_interruptible(seconds: float) -> None:
    if seconds <= 0:
        return
    _raise_if_shutdown_requested()
    interrupted = _LLM_SHUTDOWN_REQUESTED.wait(timeout=seconds)
    if interrupted:
        raise RuntimeError("LLM client interrupted by shutdown")


@contextmanager
def collect_llm_telemetry(collector: Optional[Callable[[dict[str, Any]], None]]):
    token = _LLM_TELEMETRY_COLLECTOR.set(collector)
    try:
        yield
    finally:
        _LLM_TELEMETRY_COLLECTOR.reset(token)


@contextmanager
def llm_process(process_name: str):
    token = _LLM_PROCESS.set((process_name or "unspecified").strip() or "unspecified")
    try:
        yield
    finally:
        _LLM_PROCESS.reset(token)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit_llm_telemetry(payload: dict[str, Any]) -> None:
    collector = _LLM_TELEMETRY_COLLECTOR.get()
    if collector is None:
        return
    try:
        collector(payload)
    except Exception:  # noqa: BLE001
        logger.debug("LLM telemetry collector raised; ignoring", exc_info=True)


def _extract_usage_payload(usage_obj: Any) -> dict[str, Optional[int]]:
    if usage_obj is None:
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}

    if isinstance(usage_obj, dict):
        prompt = usage_obj.get("prompt_tokens") or usage_obj.get("input_tokens")
        completion = usage_obj.get("completion_tokens") or usage_obj.get("output_tokens")
        total = usage_obj.get("total_tokens")
    else:
        prompt = getattr(usage_obj, "prompt_tokens", None) or getattr(usage_obj, "input_tokens", None)
        completion = getattr(usage_obj, "completion_tokens", None) or getattr(usage_obj, "output_tokens", None)
        total = getattr(usage_obj, "total_tokens", None)

    prompt_i = int(prompt) if isinstance(prompt, (int, float)) else None
    completion_i = int(completion) if isinstance(completion, (int, float)) else None
    total_i = int(total) if isinstance(total, (int, float)) else None
    if total_i is None and prompt_i is not None and completion_i is not None:
        total_i = prompt_i + completion_i

    return {
        "prompt_tokens": prompt_i,
        "completion_tokens": completion_i,
        "total_tokens": total_i,
    }


def _sanitize_for_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_sanitize_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_json(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _sanitize_for_json(v) for k, v in value.items()}

    # Fallback keeps telemetry serializable while preserving debug signal.
    return str(value)


def _build_request_messages_snapshot(messages: list[dict]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role", "unknown"))
        content = _sanitize_for_json(msg.get("content", ""))
        row: dict[str, Any] = {"role": role, "content": content}

        # Preserve any additional message keys for reproducibility.
        for key, value in msg.items():
            if key in {"role", "content"}:
                continue
            row[str(key)] = _sanitize_for_json(value)

        rows.append(row)
    return rows


def _get_openai_client():
    """Return a cached, configured openai.OpenAI client."""
    global _openai_client
    if _openai_client is None:
        import openai  # noqa: PLC0415
        client_kwargs = {"api_key": OPENAI_API_KEY}
        if OPENAI_BASE_URL:
            client_kwargs["base_url"] = OPENAI_BASE_URL
        _openai_client = openai.OpenAI(**client_kwargs)
    return _openai_client


def _get_anthropic_client():
    """Return a cached, configured anthropic.Anthropic client."""
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic  # noqa: PLC0415
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def _get_github_client():
    """Return a cached, configured openai.OpenAI client pointing to GitHub Models."""
    global _github_client
    if _github_client is None:
        token = GITHUB_TOKEN or OPENAI_API_KEY
        if not token:
            raise ValueError("GITHUB_TOKEN (or OPENAI_API_KEY) is required for GitHub Models requests")

        import openai  # noqa: PLC0415
        _github_client = openai.OpenAI(
            base_url="https://models.github.ai/inference",
            api_key=token,
        )
    return _github_client


# ---------------------------------------------------------------------------
# Internal state for rate-limit pausing
# ---------------------------------------------------------------------------

_last_call_time: float = 0.0


def _clip_text(text: str) -> str:
    if len(text) <= LLM_TRACE_MAX_CHARS:
        return text
    return f"{text[:LLM_TRACE_MAX_CHARS]}\n... [truncated {len(text) - LLM_TRACE_MAX_CHARS} chars]"


def _trace_messages(messages: list[dict], model: str) -> None:
    if not LLM_TRACE_MESSAGES:
        return

    header = f"[LLM TRACE] request model={model} message_count={len(messages)}"
    logger.info(header)
    print(header, flush=True)
    for idx, msg in enumerate(messages, start=1):
        role = str(msg.get("role", "unknown"))
        content = str(msg.get("content", ""))
        trace_text = f"[LLM TRACE] message[{idx}] role={role}\n{_clip_text(content)}"
        logger.info(trace_text)
        print(trace_text, flush=True)


def _trace_response(model: str, text: str) -> None:
    if not LLM_TRACE_MESSAGES:
        return
    trace_text = f"[LLM TRACE] response model={model}\n{_clip_text(text)}"
    logger.info(trace_text)
    print(trace_text, flush=True)


def _enforce_pause() -> None:
    """Sleep until at least API_PAUSE_SECONDS have elapsed since the last call."""
    global _last_call_time
    elapsed = time.time() - _last_call_time
    remaining = API_PAUSE_SECONDS - elapsed
    if remaining > 0:
        logger.debug("Rate-limit pause: sleeping %.1f s", remaining)
        _sleep_interruptible(remaining)
    _last_call_time = time.time()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_llm(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: int = LLM_MAX_TOKENS,
) -> str:
    """
    Send *messages* to the specified LLM and return the text response.

    Supports OpenAI models (``gpt-*``), Anthropic models (``claude-*``),
    and GitHub Models (e.g., ``deepseek/*``).
    An artificial pause is enforced before each call.
    Retries up to 3 times with exponential backoff (2/4/8 s) on transient errors.

    Parameters
    ----------
    messages : list[dict]
        List of ``{"role": ..., "content": ...}`` dicts.
    model : str, optional
        Override the default model from config.
    temperature : float, optional
        Override the default temperature from config.
    max_tokens : int
        Maximum tokens in the model's response.

    Returns
    -------
    str
        The model's text response.
    """
    _raise_if_shutdown_requested()
    _enforce_pause()

    model = _normalize_model_name(model or DEFAULT_MODEL)
    temperature = temperature if temperature is not None else TEMPERATURE
    logger.info(
        "LLM request started: model=%s temperature=%.2f max_tokens=%d messages=%d",
        model,
        temperature,
        max_tokens,
        len(messages),
    )
    _trace_messages(messages, model)
    request_messages = _build_request_messages_snapshot(messages)

    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES + 1):
        _raise_if_shutdown_requested()
        started_at = _utc_now_iso()
        started_perf = time.perf_counter()
        try:
            # When OPENAI_BASE_URL is set (e.g. Poe), use OpenAI-compatible client for all models
            if OPENAI_BASE_URL and OPENAI_API_KEY:
                logger.info("LLM provider selected: openai-compatible (base_url=%s, model=%s)", OPENAI_BASE_URL, model)
                result = _query_openai(messages, model, temperature, max_tokens, provider_label="openai-compatible")
                _emit_llm_telemetry(
                    {
                        "started_at": started_at,
                        "ended_at": _utc_now_iso(),
                        "elapsed_ms": round((time.perf_counter() - started_perf) * 1000, 2),
                        "provider": result["provider"],
                        "model": model,
                        "temperature": float(temperature),
                        "max_tokens": int(max_tokens),
                        "message_count": int(len(messages)),
                        "attempt": int(attempt + 1),
                        "success": True,
                        "process": _LLM_PROCESS.get(),
                        "usage": result["usage"],
                        "request_messages": request_messages,
                        "error": None,
                    }
                )
                return str(result["text"])

            if model.startswith("claude"):
                logger.info("LLM provider selected: anthropic (model=%s)", model)
                result = _query_anthropic(messages, model, temperature, max_tokens)
                _emit_llm_telemetry(
                    {
                        "started_at": started_at,
                        "ended_at": _utc_now_iso(),
                        "elapsed_ms": round((time.perf_counter() - started_perf) * 1000, 2),
                        "provider": result["provider"],
                        "model": model,
                        "temperature": float(temperature),
                        "max_tokens": int(max_tokens),
                        "message_count": int(len(messages)),
                        "attempt": int(attempt + 1),
                        "success": True,
                        "process": _LLM_PROCESS.get(),
                        "usage": result["usage"],
                        "request_messages": request_messages,
                        "error": None,
                    }
                )
                return str(result["text"])

            if _should_use_github_models(model):
                logger.info("LLM provider selected: github-models (model=%s)", model)
                result = _query_github(messages, model, temperature, max_tokens)
                _emit_llm_telemetry(
                    {
                        "started_at": started_at,
                        "ended_at": _utc_now_iso(),
                        "elapsed_ms": round((time.perf_counter() - started_perf) * 1000, 2),
                        "provider": result["provider"],
                        "model": model,
                        "temperature": float(temperature),
                        "max_tokens": int(max_tokens),
                        "message_count": int(len(messages)),
                        "attempt": int(attempt + 1),
                        "success": True,
                        "process": _LLM_PROCESS.get(),
                        "usage": result["usage"],
                        "request_messages": request_messages,
                        "error": None,
                    }
                )
                return str(result["text"])

            try:
                logger.info("LLM provider selected: openai (model=%s)", model)
                result = _query_openai(messages, model, temperature, max_tokens)
                _emit_llm_telemetry(
                    {
                        "started_at": started_at,
                        "ended_at": _utc_now_iso(),
                        "elapsed_ms": round((time.perf_counter() - started_perf) * 1000, 2),
                        "provider": result["provider"],
                        "model": model,
                        "temperature": float(temperature),
                        "max_tokens": int(max_tokens),
                        "message_count": int(len(messages)),
                        "attempt": int(attempt + 1),
                        "success": True,
                        "process": _LLM_PROCESS.get(),
                        "usage": result["usage"],
                        "request_messages": request_messages,
                        "error": None,
                    }
                )
                return str(result["text"])
            except Exception as openai_exc:  # noqa: BLE001
                if (GITHUB_TOKEN or OPENAI_API_KEY) and _is_region_block_error(openai_exc):
                    fallback_model = _normalize_model_name(GITHUB_FALLBACK_MODEL)
                    logger.warning(
                        "OpenAI request blocked by region policy; retrying via GitHub Models with %s",
                        fallback_model,
                    )
                    result = _query_github(messages, fallback_model, temperature, max_tokens)
                    _emit_llm_telemetry(
                        {
                            "started_at": started_at,
                            "ended_at": _utc_now_iso(),
                            "elapsed_ms": round((time.perf_counter() - started_perf) * 1000, 2),
                            "provider": result["provider"],
                            "model": fallback_model,
                            "temperature": float(temperature),
                            "max_tokens": int(max_tokens),
                            "message_count": int(len(messages)),
                            "attempt": int(attempt + 1),
                            "success": True,
                            "process": _LLM_PROCESS.get(),
                            "usage": result["usage"],
                            "request_messages": request_messages,
                            "error": None,
                        }
                    )
                    return str(result["text"])
                raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            _emit_llm_telemetry(
                {
                    "started_at": started_at,
                    "ended_at": _utc_now_iso(),
                    "elapsed_ms": round((time.perf_counter() - started_perf) * 1000, 2),
                    "provider": None,
                    "model": model,
                    "temperature": float(temperature),
                    "max_tokens": int(max_tokens),
                    "message_count": int(len(messages)),
                    "attempt": int(attempt + 1),
                    "success": False,
                    "process": _LLM_PROCESS.get(),
                    "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
                    "request_messages": request_messages,
                    "error": str(exc),
                }
            )
            if _is_context_length_error(exc):
                logger.error("LLM call failed due to context length overflow; not retrying same payload")
                raise
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s – retrying in %ds",
                    attempt + 1, _MAX_RETRIES, exc, delay,
                )
                _sleep_interruptible(delay)
            else:
                logger.error("LLM call failed after %d retries: %s", _MAX_RETRIES, exc)

    raise RuntimeError(f"LLM query failed after {_MAX_RETRIES} retries") from last_exc


def _is_region_block_error(exc: Exception) -> bool:
    """Return True when the API error indicates unsupported country/region."""
    err_text = str(exc).lower()
    return (
        "unsupported_country_region_territory" in err_text
        or "country, region, or territory not supported" in err_text
    )


def _is_context_length_error(exc: Exception) -> bool:
    err_text = str(exc).lower()
    return (
        "context_length_exceeded" in err_text
        or "message is too long" in err_text
        or "context length" in err_text
    )


def _normalize_model_name(model: str) -> str:
    """Map UI-friendly aliases to provider-specific model identifiers."""
    normalized = (model or "").strip()

    # Poe expects the public bot name in the model field.
    if OPENAI_BASE_URL and "api.poe.com" in OPENAI_BASE_URL.lower():
        poe_alias_map = {
            "deepseek-v3.2": "DeepSeek-V3.2",
            "deepseek v3.2": "DeepSeek-V3.2",
            "deepseek_v3.2": "DeepSeek-V3.2",
            "deepseek/v3.2": "DeepSeek-V3.2",
            "deepseek-v4-flash": "DeepSeek-V3.2",
        }
        return poe_alias_map.get(normalized.lower(), normalized)

    # For other OpenAI-compatible providers, pass model name as-is.
    if OPENAI_BASE_URL:
        return normalized
    alias_map = {
        "gpt-4o": "openai/gpt-4o",
        "gpt-4o-mini": "openai/gpt-4o-mini",
        "o4-mini": "openai/o4-mini",
    }
    return alias_map.get(normalized.lower(), normalized)


def _should_use_github_models(model: str) -> bool:
    """Return True if this model should be called via GitHub Models endpoint."""
    if OPENAI_BASE_URL and "models.github.ai" not in OPENAI_BASE_URL.lower():
        return False

    lowered = model.lower()
    if model.startswith("openai/") or model.startswith("deepseek/"):
        return True
    if lowered in {"openai/o4-mini", "openai/gpt-4o", "openai/gpt-4o-mini"}:
        return True
    if (GITHUB_TOKEN or OPENAI_API_KEY) and lowered in {"gpt-4o", "gpt-4o-mini", "o4-mini"}:
        return True
    return False


def _query_openai(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
    provider_label: str = "openai",
) -> dict[str, Any]:
    logger.info("Sending request to OpenAI Chat Completions (model=%s)", model)
    client = _get_openai_client()
    request_kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if OPENAI_BASE_URL and "api.deepseek.com" in OPENAI_BASE_URL.lower():
        if DEEPSEEK_REASONING_EFFORT:
            request_kwargs["reasoning_effort"] = DEEPSEEK_REASONING_EFFORT
        if DEEPSEEK_THINKING_ENABLED:
            request_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    response = client.chat.completions.create(
        **request_kwargs,
    )
    logger.info("Received response from OpenAI (model=%s)", model)
    text = response.choices[0].message.content or ""
    _trace_response(model, text)
    return {
        "text": text,
        "usage": _extract_usage_payload(getattr(response, "usage", None)),
        "provider": provider_label,
    }


def _query_github(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    logger.info("Sending request to GitHub Models (model=%s)", model)
    client = _get_github_client()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    logger.info("Received response from GitHub Models (model=%s)", model)
    text = response.choices[0].message.content or ""
    _trace_response(model, text)
    return {
        "text": text,
        "usage": _extract_usage_payload(getattr(response, "usage", None)),
        "provider": "github-models",
    }


def _query_anthropic(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    logger.info("Sending request to Anthropic Messages API (model=%s)", model)
    client = _get_anthropic_client()
    # Anthropic separates system prompt from user messages
    system_content = ""
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_content = msg["content"]
        else:
            chat_messages.append(msg)

    response = client.messages.create(
        model=model,
        system=system_content,
        messages=chat_messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    logger.info("Received response from Anthropic (model=%s)", model)
    text = response.content[0].text if response.content else ""
    _trace_response(model, text)
    return {
        "text": text,
        "usage": _extract_usage_payload(getattr(response, "usage", None)),
        "provider": "anthropic",
    }
