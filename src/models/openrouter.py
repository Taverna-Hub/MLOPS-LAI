"""Inferência assíncrona via Chat Completions do OpenRouter."""

import json
import math
import time

import httpx

from src.config import settings
from src.monitoring import update_trace
from src.schemas import AnaliseRisco

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(Exception):
    """Falha sanitizada com motivo estável para agregação."""

    def __init__(self, message, reason="unknown"):
        super().__init__(message)
        self.reason = reason


def capture_usage(payload):
    """Seleciona metadados; nunca copia conteúdo gerado nem detalhes de erro."""
    if not isinstance(payload, dict):
        return
    usage = payload.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("completion_tokens_details")
    details = details if isinstance(details, dict) else {}

    def numeric(value):
        return (
            value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
        )

    update_trace(
        served_model=payload.get("model") if isinstance(payload.get("model"), str) else None,
        provider=payload.get("provider") if isinstance(payload.get("provider"), str) else None,
        prompt_tokens=numeric(usage.get("prompt_tokens")),
        completion_tokens=numeric(usage.get("completion_tokens")),
        reasoning_tokens=numeric(details.get("reasoning_tokens")),
        cost_usd=numeric(usage.get("cost")),
    )


async def generate_analysis(messages: list[dict[str, str]]) -> AnaliseRisco:
    """Consulta somente o modelo configurado e valida integralmente a análise."""
    update_trace(requested_model=settings.MODEL_NAME)
    if not settings.openrouter_configured:
        raise OpenRouterError("OPENROUTER_API_KEY não configurada", "not_configured")
    update_trace(remote_attempted=True)
    started = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=settings.OPENROUTER_TIMEOUT_SECONDS) as client:
            response = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY.get_secret_value().strip()}",
                },
                json={
                    "model": settings.MODEL_NAME,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": settings.OPENROUTER_MAX_TOKENS,
                    "reasoning": {"effort": "low", "exclude": True},
                    "stream": False,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "analise_risco_lai",
                            "strict": True,
                            "schema": AnaliseRisco.model_json_schema(),
                        },
                    },
                    "provider": {"require_parameters": True},
                },
            )
            update_trace(remote_status_code=response.status_code)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Não propagar corpo/headers do provedor, que podem conter dados do pedido.
        raise OpenRouterError(
            f"OpenRouter retornou HTTP {exc.response.status_code}", "http_error"
        ) from None
    except httpx.RequestError as exc:
        raise OpenRouterError(
            f"Falha de comunicação com OpenRouter ({type(exc).__name__})",
            "timeout" if isinstance(exc, httpx.TimeoutException) else "network_error",
        ) from None

    finally:
        update_trace(remote_latency_ms=round((time.perf_counter() - started) * 1000, 3))

    update_trace(schema_valid=False)
    failure_reason = "invalid_output"
    try:
        payload = response.json()
        capture_usage(payload)
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("Resposta de erro do provedor")
        choice = payload["choices"][0]
        if choice.get("finish_reason") != "stop":
            failure_reason = "incomplete_output"
            raise ValueError("Geração incompleta ou bloqueada")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Conteúdo ausente")
        content = content.strip()
        if content.startswith("```json\n") and content.endswith("```"):
            content = content[len("```json\n") : -3].strip()
        elif content.startswith("```\n") and content.endswith("```"):
            content = content[4:-3].strip()
        result = AnaliseRisco.model_validate(json.loads(content))
        update_trace(schema_valid=True)
        return result
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise OpenRouterError(
            "Resposta do OpenRouter inválida para o contrato de análise", failure_reason
        ) from None
