# Agente SIC-LAI: Triagem Preditiva e Análise de Risco de Atraso em Pedidos da LAI

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Package Manager](https://img.shields.io/badge/dependency%20manager-uv-blueviolet.svg)](https://astral.sh/uv)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Model](https://img.shields.io/badge/SLM-Qwen2.5--0.5B--Instruct-orange.svg)](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)

Microserviço inteligente de inferência e triagem precoce que atua estritamente no momento inicial **$t_0$** (instante do protocolo) de Pedidos de Acesso à Informação (PAI) regidos pela Lei Federal nº 12.527/2011 (LAI).

O sistema estima a probabilidade de extrapolação do prazo legal de resposta (risco de `ATRASADO`), identifica os fatores geradores de risco e fornece recomendações acionáveis ao servidor do Serviço de Informação ao Cidadão (SIC).

> **Aviso de Governança Humana:** O modelo atua exclusivamente como apoio consultivo de triagem interna ao servidor público no instante $t_0$. Ele **não** responde diretamente ao cidadão, **não** julga o mérito do pedido e **não** toma decisões administrativas autônomas.

---

## 1. Linhagem e Especificação do Modelo Aberto

O projeto adota um **Small Language Model (SLM)** aberto, executado 100% localmente em CPU, garantindo independência de provedores de nuvem, custo zero de inferência e eliminação do risco de vazamento de chaves ou segredos:

| Atributo | Especificação Oficial |
| :--- | :--- |
| **Modelo Base** | [`Qwen/Qwen2.5-0.5B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct) |
| **Criador** | Alibaba Cloud / Equipe Qwen |
| **Licença** | Apache 2.0 (Permissiva comercial e acadêmica) |
| **Parâmetros** | 0.49 Bilhão (490M parâmetros) |
| **Consumo de Memória** | < 1.0 GB RAM em inferência CPU |
| **Vocabulário** | 151.646 tokens (excelente suporte nativo ao Português) |
| **Formato** | PyTorch / Safetensors FP32 nativo para CPU |
| **Pre-caching** | Pesos baixados durante o `docker build` (100% offline em runtime) |

---

## 2. Início Rápido: Como Rodar em 1 Comando

### Pré-requisitos
- **Docker** e **Docker Compose** instalados (ou Python 3.11+ e `uv`).
- Tempo estimado de inicialização: **~30 segundos**.

### Execução via Docker Compose (Recomendado)
```bash
docker compose up --build
```
O serviço estará pronto e respondendo em: `http://localhost:8000`

---

## 3. Checagem Rápida

Siga os três passos abaixo para validar todo o serviço:

### Passo 1: Verificar a Saúde do Serviço
```bash
curl -s http://localhost:8000/health
```
**Resposta Esperada (HTTP 200):**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "model": "Qwen/Qwen2.5-0.5B-Instruct",
  "device": "cpu"
}
```

### Passo 2: Executar Predição de Exemplo (Caso de Alto Risco)
```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "protocolo": "PAI-2026-001",
    "data_registro": "2026-09-21T10:00:00Z",
    "orgao_destinatario": "Ministério da Saúde (MS)",
    "origem_solicitacao": "Internet",
    "forma_resposta": "E-mail",
    "resumo_solicitacao": "Microdados de contratos de vacinação 2020 a 2024",
    "detalhamento_solicitacao": "Solicito a íntegra de todas as notas fiscais, termos aditivos, relatórios de auditoria e tabelas orçamentárias detalhadas referentes a aquisição de vacinas e insumos hospitalares entre os anos de 2020 e 2024 em formato CSV bruto descompactado.",
    "prazo_atendimento": "2026-10-11"
  }'
```
**Resposta Esperada (HTTP 200):**
```json
{
  "protocolo": "PAI-2026-001",
  "nivel_risco": "ALTO",
  "score_risco": 0.88,
  "fatores_risco": [
    "Volume extenso de dados históricos requerendo consolidação entre diferentes secretarias",
    "Demanda por extração customizada de relatórios orçamentários e notas fiscais",
    "Elevado risco de desmembramento entre áreas técnicas gerando atraso"
  ],
  "recomendacao_sic": "Sinalizar como ACOMPANHAMENTO PRIORITÁRIO. Articular reunião de alinhamento com a área técnica orçamentária dentro dos primeiros 3 dias úteis.",
  "tempo_processamento_ms": 15.2
}
```

### Passo 3: Testar Rejeição de Vazamento Temporal (Data Leakage em $t_0$)
Envie uma requisição contendo campo proibido posterior a $t_0$ (ex: `data_resposta`):
```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "protocolo": "PAI-2026-ERR1",
    "data_registro": "2026-09-21T08:00:00Z",
    "orgao_destinatario": "Ministério da Fazenda",
    "origem_solicitacao": "Internet",
    "forma_resposta": "E-mail",
    "resumo_solicitacao": "Dados fiscais",
    "detalhamento_solicitacao": "Solicito dados do tesouro nacional.",
    "data_resposta": "2026-10-02"
  }'
```
**Resposta Esperada (HTTP 422 Unprocessable Entity):**
```json
{
  "detail": [
    {
      "loc": ["body", "data_resposta"],
      "msg": "Violação de momento t0: o campo 'data_resposta' configura vazamento temporal (data leakage) e é proibido nesta API.",
      "type": "value_error.temporal_leakage"
    }
  ]
}
```

---

## 4. Execução Local com `uv` ou `just`

Caso deseje executar fora do Docker:

```bash
# 1. Instalar dependências fixadas
uv sync --extra dev

# 2. Rodar linter
uv run ruff check .

# 3. Iniciar servidor da API
uv run uvicorn src.app:app --host 0.0.0.0 --port 8000
```

Caso tenha o `just` instalado:
- `just run` — Executa o servidor local
- `just lint` — Verifica qualidade do código com Ruff
- `just docker-up` — Sobe via Docker Compose em background

Documentação interativa Swagger UI disponível em: `http://localhost:8000/docs`

---

## 5. Prevenção Rigorosa de Vazamento Temporal ($t_0$)

Conforme estabelecido na modelagem de negócio da CGU e no PRD:
- **Campos Autorizados em $t_0$:** `protocolo`, `data_registro`, `orgao_destinatario`, `origem_solicitacao`, `forma_resposta`, `resumo_solicitacao`, `detalhamento_solicitacao`, `prazo_atendimento`.
- **Campos Proibidos (Disparam HTTP 422):** `data_resposta`, `decisao`, `especificacao_decisao`, `situacao`, `foi_prorrogado`, `foi_reencaminhado`.
- **Regra de Abstenção:** Caso campos essenciais venham em branco ou ininteligíveis, o sistema retorna `nivel_risco: "INDETERMINADO"` e `score_risco: 0.0`.

---

## 6. Governança e Uso Transparente de IA

> **Declaração de Uso de Inteligência Artificial:**
> Em conformidade com as diretrizes de integridade acadêmica e boas práticas da disciplina de MLOps:
> - O desenvolvimento deste microsserviço contou com o auxílio assistido de Large Language Models (como o Google Antigravity / Gemini) para suporte na estruturação do scaffold de código, elaboração de casos de testes unitários e otimização dos templates de prompt.
> - Toda a arquitetura do software, validações anti-leakage de momento $t_0$, parametrização do SLM local (`Qwen2.5-0.5B-Instruct`), configuração de containerização e conformidade com o PRD foram projetadas, auditadas e validadas pela equipe do projeto.

---

## 7. Licença

Este projeto é distribuído sob a licença **MIT**. Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.