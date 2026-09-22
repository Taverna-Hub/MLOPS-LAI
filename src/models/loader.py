"""Carregamento seguro e gerenciamento do ciclo de vida do modelo Qwen2.5."""

import logging
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

from src.config import settings

logger = logging.getLogger("sic_lai.model")

_pipeline_instance: Any = None
_model_instance: Any = None
_tokenizer_instance: Any = None


def load_model(model_name: str | None = None) -> tuple[Any, Any]:
    """Carrega o modelo e o tokenizer em memória (CPU Singleton)."""
    global _model_instance, _tokenizer_instance

    target_model = model_name or settings.MODEL_NAME

    if _model_instance is not None and _tokenizer_instance is not None:
        return _model_instance, _tokenizer_instance

    if not settings.USE_SLM:
        logger.info("Inferência de SLM desativada via USE_SLM=False.")
        return None, None

    logger.info("Carregando modelo e tokenizer: %s no device %s...", target_model, settings.DEVICE)
    try:
        _tokenizer_instance = AutoTokenizer.from_pretrained(
            target_model,
            local_files_only=settings.LOCAL_FILES_ONLY,
        )
        _model_instance = AutoModelForCausalLM.from_pretrained(
            target_model,
            torch_dtype=torch.float32,
            low_cpu_mem_usage=True,
            local_files_only=settings.LOCAL_FILES_ONLY,
        )
        logger.info("Modelo %s carregado com sucesso!", target_model)
        return _model_instance, _tokenizer_instance
    except Exception as exc:
        logger.warning(
            "Modelo %s não pôde ser carregado imediatamente (%s). O serviço utilizará a heurística analítica de negócio.",
            target_model,
            exc,
        )
        return None, None


def get_pipeline(model_name: str | None = None) -> Any:
    """Retorna pipeline de geração de texto inicializado ou None para fallback."""
    global _pipeline_instance

    target_model = model_name or settings.MODEL_NAME

    if _pipeline_instance is not None:
        return _pipeline_instance

    model, tokenizer = load_model(target_model)
    if model is None or tokenizer is None:
        return None

    try:
        _pipeline_instance = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            device="cpu",
        )
        return _pipeline_instance
    except Exception as exc:
        logger.warning("Falha ao instanciar pipeline de inferência (%s).", exc)
        return None
