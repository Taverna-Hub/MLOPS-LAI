"""Aplicação FastAPI para o serviço de inferência e triagem Agente SIC-LAI."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST

from src.agent.analyzer import analisar_pedido
from src.config import settings
from src.metrics import Metrics
from src.monitoring import MonitoringMiddleware, update_trace
from src.schemas import (
    FORBIDDEN_T0_FIELDS,
    HealthResponse,
    PedidoLAIRequest,
    TemporalLeakageError,
    TriagemLAIResponse,
)

logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sic_lai.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicia o serviço sem carregar pesos nem consultar o provedor remoto."""
    logger.info("Iniciando Agente SIC-LAI (OpenRouter, modelo: %s)...", settings.MODEL_NAME)
    if not settings.openrouter_configured:
        logger.warning("OPENROUTER_API_KEY ausente: pedidos abertos usarão fallback heurístico.")
    yield
    logger.info("Encerrando Agente SIC-LAI...")


app = FastAPI(
    title="Agente SIC-LAI: Triagem Preditiva em t0",
    description=(
        "Microserviço de triagem preditiva e estimativa de risco de extrapolação de prazo "
        "em Pedidos de Acesso à Informação (PAI), atuando no momento de protocolo (t0)."
    ),
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.state.monitoring_metrics = Metrics()
app.add_middleware(MonitoringMiddleware, observer=app.state.monitoring_metrics.observe)


@app.get("/metrics", tags=["Diagnóstico"], summary="Métricas em formato Prometheus")
async def metrics() -> Response:
    return Response(
        content=app.state.monitoring_metrics.render(),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )


@app.exception_handler(TemporalLeakageError)
async def temporal_leakage_exception_handler(request: Request, exc: TemporalLeakageError):
    """Retorna erro 422 padronizado para tentativas de vazamento temporal."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": [
                {
                    "loc": ["body", exc.field_name],
                    "msg": exc.message,
                    "type": "value_error.temporal_leakage",
                }
            ]
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Tratamento customizado para interceptar vazamentos temporais dentro dos erros do Pydantic."""
    details = []
    for error in exc.errors():
        ctx_error = (
            error.get("ctx", {}).get("error") if isinstance(error.get("ctx"), dict) else None
        )
        field_name = None

        if isinstance(ctx_error, TemporalLeakageError):
            field_name = ctx_error.field_name
        elif error.get("loc") and error.get("loc")[-1] in FORBIDDEN_T0_FIELDS:
            field_name = str(error.get("loc")[-1])
        else:
            msg_str = str(error.get("msg", ""))
            for f in FORBIDDEN_T0_FIELDS:
                if f in msg_str:
                    field_name = f
                    break

        if field_name and field_name in FORBIDDEN_T0_FIELDS:
            details.append(
                {
                    "loc": ["body", field_name],
                    "msg": FORBIDDEN_T0_FIELDS[field_name],
                    "type": "value_error.temporal_leakage",
                }
            )
        else:
            details.append(error)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": details},
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Diagnóstico"],
    summary="Verifica o serviço e a configuração da inferência remota",
)
async def health_check() -> HealthResponse:
    """Retorna o status operacional do container e o modelo configurado."""
    return HealthResponse(
        status="healthy" if settings.openrouter_configured else "degraded",
        version=settings.VERSION,
        model=settings.MODEL_NAME,
        device="remote",
    )


@app.post(
    "/predict",
    response_model=TriagemLAIResponse,
    tags=["Triagem e Predição"],
    summary="Analisa o risco de atraso em t0 para o pedido de informação",
)
async def predict(pedido: PedidoLAIRequest) -> TriagemLAIResponse:
    """Recebe um pedido no momento inicial t0 e calcula o risco de descumprimento de prazo."""
    update_trace(
        orgao_destinatario=pedido.orgao_destinatario,
        origem_solicitacao=pedido.origem_solicitacao,
        forma_resposta=pedido.forma_resposta,
        resumo_chars=len(pedido.resumo_solicitacao),
        detalhamento_chars=len(pedido.detalhamento_solicitacao),
    )
    result = await analisar_pedido(pedido)
    update_trace(
        analysis_ms=result.tempo_processamento_ms,
        nivel_risco=result.nivel_risco.value,
        score_risco=result.score_risco,
        fatores_count=len(result.fatores_risco),
    )
    return result
