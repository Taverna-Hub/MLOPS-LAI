"""Schemas de validação Pydantic com garantia anti-leakage para momento t0."""

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NivelRiscoEnum(str, Enum):
    """Níveis de risco calculados para pedidos de acesso à informação."""

    ALTO = "ALTO"
    MEDIO = "MEDIO"
    BAIXO = "BAIXO"
    INDETERMINADO = "INDETERMINADO"


FORBIDDEN_T0_FIELDS = {
    "data_resposta": "Violação de momento t0: o campo 'data_resposta' configura vazamento temporal (data leakage) e é proibido nesta API.",
    "decisao": "Violação de momento t0: o campo 'decisao' configura vazamento temporal (data leakage) e é proibido nesta API.",
    "especificacao_decisao": "Violação de momento t0: o campo 'especificacao_decisao' configura vazamento temporal (data leakage) e é proibido nesta API.",
    "situacao": "Violação de momento t0: o campo 'situacao' configura vazamento temporal (data leakage) e é proibido nesta API.",
    "foi_prorrogado": "Violação de momento t0: o campo 'foi_prorrogado' configura vazamento temporal (data leakage) e é proibido nesta API.",
    "foi_reencaminhado": "Violação de momento t0: o campo 'foi_reencaminhado' configura vazamento temporal (data leakage) e é proibido nesta API.",
}


class TemporalLeakageError(ValueError):
    """Exceção levantada quando campos posteriores a t0 são enviados."""

    def __init__(self, field_name: str, message: str):
        super().__init__(message)
        self.field_name = field_name
        self.message = message


class PedidoLAIRequest(BaseModel):
    """Payload de entrada permitido estritamente no momento t0."""

    protocolo: str = Field(..., description="Identificador único/anonimizado do pedido")
    data_registro: datetime = Field(..., description="Data e hora de registro no sistema Fala.BR")
    orgao_destinatario: str = Field(..., description="Órgão ou autarquia destinatária")
    origem_solicitacao: str = Field(..., description="Canal de entrada (ex: Internet, Presencial)")
    forma_resposta: str = Field(
        ..., description="Meio pretendido de resposta (ex: E-mail, Sistema)"
    )
    resumo_solicitacao: str = Field(..., description="Assunto sumário do pedido")
    detalhamento_solicitacao: str = Field(..., description="Texto integral da solicitação")
    prazo_atendimento: date | None = Field(default=None, description="Data limite inicial estimada")

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def check_temporal_leakage(cls, data: Any) -> Any:
        """Verifica a presença de qualquer campo que configure vazamento temporal."""
        if isinstance(data, dict):
            for forbidden_field, error_msg in FORBIDDEN_T0_FIELDS.items():
                if forbidden_field in data:
                    raise TemporalLeakageError(forbidden_field, error_msg)
        return data


class TriagemLAIResponse(BaseModel):
    """Esquema de resposta da análise de triagem e risco em t0."""

    protocolo: str
    nivel_risco: NivelRiscoEnum
    score_risco: float = Field(..., ge=0.0, le=1.0)
    fatores_risco: list[str]
    recomendacao_sic: str
    tempo_processamento_ms: float


class HealthResponse(BaseModel):
    """Esquema de resposta do endpoint /health."""

    status: str
    version: str
    model: str
    device: str
