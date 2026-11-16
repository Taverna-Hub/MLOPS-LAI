"""Inferência assíncrona via Chat Completions do OpenRouter."""

import json

import httpx

from src.config import settings
from src.schemas import AnaliseRisco

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(Exception):
    """Falha de configuração, transporte ou contrato da inferência remota."""


async def generate_analysis(messages: list[dict[str, str]]) -> AnaliseRisco:
    """Consulta somente o modelo configurado e valida integralmente a análise."""
    if not settings.openrouter_configured:
        raise OpenRouterError("OPENROUTER_API_KEY não configurada")

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
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Não propagar corpo/headers do provedor, que podem conter dados do pedido.
        raise OpenRouterError(f"OpenRouter retornou HTTP {exc.response.status_code}") from None
    except httpx.RequestError as exc:
        raise OpenRouterError(
            f"Falha de comunicação com OpenRouter ({type(exc).__name__})"
        ) from None

    try:
        payload = response.json()
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("Resposta de erro do provedor")
        choice = payload["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("Geração incompleta ou bloqueada")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Conteúdo ausente")
        content = content.strip()
        if content.startswith("```json\n") and content.endswith("```"):
            content = content[len("```json\n") : -3].strip()
        elif content.startswith("```\n") and content.endswith("```"):
            content = content[4:-3].strip()
        return AnaliseRisco.model_validate(json.loads(content))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise OpenRouterError(
            "Resposta do OpenRouter inválida para o contrato de análise"
        ) from None
