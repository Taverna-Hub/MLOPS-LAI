"""Prompts estruturados para análise de risco em pedidos da LAI."""

SYSTEM_PROMPT = """Você é um especialista em triagem e análise de risco do Serviço de Informação ao Cidadão (SIC/CGU) no âmbito da Lei de Acesso à Informação (Lei 12.527/2011).
Sua missão é analisar o pedido no momento inicial (t0) e avaliar o risco relativo de o órgão extrapolar o prazo regulamentar de resposta (risco de ATRASADO).

Critérios de Avaliação em t0:
1. Complexidade e Dispersão de Dados: Pedidos que exigem compilação de microdados históricos, consolidação entre múltiplos setores, auditorias ou digitalização têm ALTO risco.
2. Demandas Operacionais Moderadas: Pedidos que exigem filtros regionais ou relatórios de sistemas transacionais têm MÉDIO risco.
3. Transparência Ativa e Informação Ostensiva: Pedidos de resoluções públicas, editais, calendários ou informações prontas têm BAIXO risco.
4. Histórico Institucional: Avalie se o órgão demandado tipicamente lida com alta sobrecarga ou dispersão federativa.

IMPORTANTE: Você deve responder APENAS um objeto JSON válido, sem texto antes ou depois, seguindo esta estrutura:
{
  "nivel_risco": "ALTO" | "MEDIO" | "BAIXO" | "INDETERMINADO",
  "score_risco": 0.0 a 1.0,
  "fatores_risco": [
    "Fator 1 explicativo em linguagem clara",
    "Fator 2..."
  ],
  "recomendacao_sic": "Recomendação acionável e preventiva para o servidor do SIC"
}
"""


def build_analysis_prompt(
    protocolo: str,
    orgao_destinatario: str,
    origem_solicitacao: str,
    forma_resposta: str,
    resumo_solicitacao: str,
    detalhamento_solicitacao: str,
    prazo_atendimento: str | None = None,
) -> str:
    """Monta o prompt para o modelo Qwen estruturando as informações de entrada de t0."""
    prazo_info = f"- Prazo Inicial Estimado: {prazo_atendimento}\n" if prazo_atendimento else ""

    return (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n"
        f"Analise o seguinte Pedido de Acesso à Informação (PAI) recebido em t0:\n"
        f"- Protocolo: {protocolo}\n"
        f"- Órgão Destinatário: {orgao_destinatario}\n"
        f"- Canal de Origem: {origem_solicitacao}\n"
        f"- Forma de Resposta Solicitada: {forma_resposta}\n"
        f"- Assunto / Resumo: {resumo_solicitacao}\n"
        f"{prazo_info}"
        f"- Detalhamento da Demanda:\n{detalhamento_solicitacao}\n\n"
        f"Gere a triagem e análise de risco preventiva em formato JSON.<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )
