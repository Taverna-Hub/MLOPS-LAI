# Agente SIC-LAI

Microserviço de triagem de Pedidos de Acesso à Informação (PAI). No momento do protocolo (**t0**), estima um nível indicativo de risco de atraso, apresenta fatores de risco e recomendações para apoiar o Serviço de Informação ao Cidadão (SIC).

> **A decisão permanece humana.** O serviço não responde ao cidadão, não avalia o mérito do pedido e não toma decisões administrativas.

## Arquitetura e modelo

A API roda localmente com **FastAPI** e **Pydantic v2**. Para pedidos abertos, consulta o OpenRouter usando **`nvidia/nemotron-3.5-super-vl:free`**, com mensagens de sistema/usuário e saída estruturada por **JSON Schema**. Não há download de pesos, inferência local, Torch ou Transformers.

O [Nemotron 3.5 Super VL no OpenRouter](https://openrouter.ai/nvidia/nemotron-3.5-super-vl:free) possui 120 bilhões de parâmetros totais, 12 bilhões ativos e contexto de 1 milhão de tokens. O endpoint da NVIDIA anuncia suporte a `response_format` e `structured_outputs`. A chamada inclui `strict: true` e `provider.require_parameters: true` para exigir um endpoint compatível. A aplicação também valida a resposta com Pydantic; JSON Schema não garante que a avaliação de risco esteja correta.

O identificador `:free` tem preço de tokens de entrada e saída igual a zero, mas exige uma chave OpenRouter e está sujeito a [limites de uso](https://openrouter.ai/docs/api/reference/limits) e disponibilidade do provedor. O serviço não seleciona modelos pagos como alternativa.

Nos pedidos enviados ao modelo, órgão, protocolo, canal, forma de resposta, resumo, detalhamento e prazo opcional saem da máquina e são processados pelo provedor. O endpoint gratuito da NVIDIA orienta não enviar informações confidenciais nem dados pessoais; use exemplos fictícios ou anonimizados.

O analisador preserva o fluxo híbrido anterior:

1. Valida o contrato e bloqueia campos posteriores a t0.
2. Retorna `INDETERMINADO` para órgão vazio ou detalhamento com menos de cinco caracteres úteis.
3. Devolve diretamente as regras específicas de risco `ALTO` e `BAIXO`, e `MEDIO` quando o órgão contém “INSS”. Esses casos não consultam OpenRouter.
4. Para outros pedidos, consulta o modelo remoto e valida o resultado.
5. Usa fallback heurístico se a chave estiver ausente, houver timeout, erro HTTP, geração incompleta ou resposta inválida.

Os scores são indicativos. As regras usam valores definidos em código e não há treinamento nem calibração estatística com dados históricos. Uma resposta HTTP 200 também pode ter origem no fallback.

## Contrato HTTP

- `POST /predict`: retorna `protocolo`, `nivel_risco`, `score_risco`, `fatores_risco`, `recomendacao_sic` e `tempo_processamento_ms`.
- `GET /health`: retorna versão, modelo e `device: "remote"`. O status é `healthy` quando há chave configurada e `degraded` quando falta a chave. O HTTP permanece 200: é uma verificação do serviço e da configuração, não uma chamada de teste ao OpenRouter nem uma validação da chave.
- `/docs` e `/redoc`: documentação dos contratos.
- `GET /metrics`: medições HTTP e de inferência em formato Prometheus.
- Campos `data_resposta`, `decisao`, `especificacao_decisao`, `situacao`, `foi_prorrogado` e `foi_reencaminhado` são rejeitados com HTTP 422.

## Início rápido com Docker

Requer Docker Engine e Docker Compose v2. Os comandos abaixo usam Bash; no Windows, use Git Bash/WSL ou faça as requisições pelo Swagger.

```bash
git clone https://github.com/Taverna-Hub/MLOPS-LAI.git
cd MLOPS-LAI
cp .env.example .env
```

No PowerShell, a cópia equivalente é `Copy-Item .env.example .env`. Edite `.env` e preencha `OPENROUTER_API_KEY` com uma chave criada em [OpenRouter — API keys](https://openrouter.ai/settings/keys). O arquivo `.env` é ignorado pelo Git e pelo contexto de build Docker.

```bash
docker compose up --build -d
curl http://localhost:8000/health
```

A API fica em `http://localhost:8000`, e o Swagger em [http://localhost:8000/docs](http://localhost:8000/docs). A inferência remota requer internet. Sem chave, o serviço continua disponível com heurísticas e fallback.

### Pedido aberto: consulta ao OpenRouter

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "protocolo": "PAI-REMOTO-001",
    "data_registro": "2026-11-16T10:00:00Z",
    "orgao_destinatario": "Instituto Brasileiro do Meio Ambiente e dos Recursos Naturais Renováveis (IBAMA)",
    "origem_solicitacao": "Internet",
    "forma_resposta": "E-mail",
    "resumo_solicitacao": "Etapas para autorização de visita técnica",
    "detalhamento_solicitacao": "Solicito informar quais documentos são necessários para pedir autorização de visita técnica a uma unidade de conservação federal, qual setor recebe o pedido e como acompanhar a análise."
  }'
```

A resposta e a latência variam conforme o provedor. Exemplo ilustrativo do contrato, sem representar uma execução real:

```json
{
  "protocolo": "PAI-REMOTO-001",
  "nivel_risco": "MEDIO",
  "score_risco": 0.5,
  "fatores_risco": ["Necessidade de identificar o fluxo e a unidade responsável"],
  "recomendacao_sic": "Confirmar o encaminhamento com a unidade responsável e acompanhar o aceite.",
  "tempo_processamento_ms": 1500.0
}
```

O tempo inclui a tentativa de chamada remota quando ela ocorre. Para demonstrar o fallback por falta de credencial, deixe a chave vazia e recrie o serviço antes de reenviar esse pedido: o retorno será `MEDIO`, score `0.50`. Uma chave inválida ou limite HTTP 429 também aciona fallback; o motivo é registrado no console sem imprimir a chave ou o corpo da resposta do provedor.

### Regra específica: sem chamada remota

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "protocolo": "PAI-REGRA-001",
    "data_registro": "2026-11-16T10:00:00Z",
    "orgao_destinatario": "Ministério da Saúde",
    "origem_solicitacao": "Internet",
    "forma_resposta": "E-mail",
    "resumo_solicitacao": "Microdados de contratos de vacinação",
    "detalhamento_solicitacao": "Solicito notas fiscais e tabelas orçamentárias de 2020 a 2024."
  }'
```

Retorna `ALTO`, score `0.88`, pela regra existente. Para parar o serviço:

```bash
docker compose down
```

## Monitoramento da entrega

O serviço grava medidas e categorias de cada atendimento em `logs/requests.jsonl`, com timestamp UTC, UUID interno, origem do resultado e uso do OpenRouter. Não grava os textos dos pedidos e respostas. Há rotação a cada 10 MB e retenção de cinco arquivos anteriores; o Compose preserva os logs no host.

Para gerar carga e acompanhar o rastro sem Python no host:

```bash
docker compose exec -T sic-lai-service /app/.venv/bin/python -m monitoring.generate_load
curl http://localhost:8000/metrics
```

Em outro terminal, use `tail -f logs/requests.jsonl` (Bash) ou `Get-Content logs/requests.jsonl -Tail 5 -Wait` (PowerShell). A rodada tem 30 pedidos fictícios, incluindo três tentativas reais ao OpenRouter. Tokens, custo e validade da resposta ficam no rastro, permitindo distinguir inferência remota de fallback.

O [guia de monitoramento](monitoring/README.md) contém o roteiro completo, as 19 métricas, os cálculos de histogramas/boxplots/taxas, a política de retenção e os comandos de análise. A [planilha demonstrativa](monitoring/examples/monitoramento.xlsx) e os snapshots de uma rodada real estão versionados. A [checagem final da atividade](monitoring/VALIDACAO.md) relaciona os requisitos às evidências.

## Configuração e desenvolvimento

| Variável | Padrão | Finalidade |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | Vazio | Credencial para inferência remota |
| `MODEL_NAME` | `nvidia/nemotron-3.5-super-vl:free` | Modelo OpenRouter, que deve aceitar JSON Schema |
| `OPENROUTER_TIMEOUT_SECONDS` | `120` | Timeout de cada operação de rede |
| `OPENROUTER_MAX_TOKENS` | `4096` | Limite da geração, incluindo raciocínio |
| `LOG_LEVEL` | `info` | Nível dos logs |
| `MONITORING_LOG_PATH` | `logs/requests.jsonl` | Arquivo JSONL; no Compose, `/app/logs/requests.jsonl` |
| `MONITORING_MAX_BYTES` | `10000000` | Limite de rotação em bytes |
| `MONITORING_BACKUPS` | `5` | Quantidade de arquivos anteriores |

As antigas opções `DEVICE`, `USE_SLM` e `LOCAL_FILES_ONLY` foram removidas. Para executar fora do Docker, instale Python 3.11+ e `uv`, configure `.env` e rode:

```bash
uv sync --frozen --extra dev
uv run uvicorn src.app:app --host 0.0.0.0 --port 8000
```

Verificações, sem consumir a API:

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run ruff format src monitoring tests --check
```

Os testes usam transporte HTTP simulado para verificar JSON Schema, autenticação, erros, fallback e preservação das regras. Não substituem uma avaliação de qualidade com pedidos representativos nem uma chamada real com a chave do usuário.

```text
src/
├── app.py              # API FastAPI
├── config.py           # Configuração e chave protegida por SecretStr
├── schemas.py          # Contratos e validação anti-leakage
├── agent/
│   ├── analyzer.py     # Regras, inferência remota e fallback
│   └── prompt.py       # Mensagens de sistema e usuário
└── models/
    └── openrouter.py   # Cliente HTTP assíncrono e validação da resposta
```

## Documentação do projeto

- [`docs/GUIA_REPRODUCAO.md`](docs/GUIA_REPRODUCAO.md): guia de negócio, dados e implementação.
- [`docs/PRD.md`](docs/PRD.md): especificação original da entrega local; veja a nota de atualização no início.
- [`docs/LAI_Entendimento_Negocio.pdf`](docs/LAI_Entendimento_Negocio.pdf): contexto de negócio.

## Uso de Inteligência Artificial

Foram utilizados agentes de IA do **OpenCode** e do **Antigravity** como apoio durante a execução do trabalho. Os agentes foram utilizados como escritores de código em pair programming com a equipe. Também foram utilizados para auxiliar na escolha do modelo de LLM utilizado no projeto, organizar e revisar a documentação, e estruturar um guia reproduzível de execução.

Na entrega de monitoramento, o **Codex** (OpenAI) apoiou a implementação do registro, das métricas e da análise. O **Claude Code** (Anthropic) foi usado na revisão final da entrega e no ajuste da documentação.

As respostas foram tratadas como sugestões, não como fonte definitiva. Todo código gerado por IA foi revisado e aprovado por uma pessoa da equipe antes de ser incorporado. A equipe também comparou as descrições com o código e os documentos do projeto, revisou comandos e exemplos e registrou divergências entre a implementação atual e especificações anteriores do PRD. As decisões de domínio, a validação do conteúdo e a responsabilidade pela entrega permanecem com a equipe.

Como artefato da implementação do projeto, temos o [PRD do Agente SIC-LAI](docs/PRD.md).

## Licença

Distribuído sob a licença [MIT](LICENSE).
