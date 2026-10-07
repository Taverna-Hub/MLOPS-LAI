# Agente SIC-LAI

Microserviço local de triagem de Pedidos de Acesso à Informação (PAI). No momento do protocolo (**t0**), estima um nível indicativo de risco de atraso e apresenta fatores de risco e uma recomendação para apoiar o acompanhamento pelo Serviço de Informação ao Cidadão (SIC).

> **A decisão permanece humana.** O serviço não responde ao cidadão, não avalia o mérito do pedido e não toma decisões administrativas.

## O que o serviço faz

- `GET /health`: informa o estado e a configuração do serviço.
- `POST /predict`: recebe os dados do pedido disponíveis em t0 e retorna `nivel_risco`, `score_risco`, `fatores_risco`, `recomendacao_sic` e `tempo_processamento_ms`.
- Rejeita com HTTP 422 campos que representam eventos posteriores a t0: `data_resposta`, `decisao`, `especificacao_decisao`, `situacao`, `foi_prorrogado` e `foi_reencaminhado`.
- Abstém-se quando o órgão ou o detalhamento estão vazios ou quando o detalhamento tem menos de cinco caracteres.

## Arquitetura e modelo

O serviço usa **FastAPI**, **Pydantic v2** e inferência local em CPU com `Qwen/Qwen2.5-0.5B-Instruct`. A análise combina regras heurísticas para alguns padrões reconhecidos e o SLM para solicitações mais abertas, com fallback heurístico se a inferência falhar.

Os scores atuais são indicativos: as heurísticas usam valores definidos em código e o projeto não inclui treinamento nem calibração estatística do modelo com dados históricos. A linhagem do SLM é o repositório [`Qwen/Qwen2.5-0.5B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct), licença Apache 2.0.

## Código-fonte

```text
src/
├── app.py              # API FastAPI: /health e /predict
├── config.py           # Configuração por variáveis de ambiente
├── schemas.py          # Contratos Pydantic e validação anti-leakage
├── agent/
│   ├── analyzer.py     # Regras, inferência e fallback
│   └── prompt.py       # Prompt do SLM
└── models/
    └── loader.py       # Carregamento do Qwen e pipeline local
```

O `pyproject.toml` e o `uv.lock` definem as dependências; `Dockerfile` e `docker-compose.yml` empacotam e executam o serviço; `justfile` reúne atalhos de desenvolvimento.

## Início rápido

Com Docker Engine e Docker Compose v2 instalados, clone o repositório e inicie o serviço:

```bash
git clone https://github.com/Taverna-Hub/MLOPS-LAI.git
cd MLOPS-LAI
docker compose up --build -d
```

A primeira construção leva aproximadamente **5–15 minutos**, conforme máquina e conexão, e baixa cerca de 1 GB de pesos do modelo. Não é necessário instalar Python no host para este caminho. A API fica em `http://localhost:8000` e o Swagger em [`http://localhost:8000/docs`](http://localhost:8000/docs).

Verifique se a API respondeu:

```bash
curl http://localhost:8000/health
```

Em outro terminal, envie uma primeira predição:

O comando `curl` abaixo é para Bash; no Windows, execute-o no Git Bash ou WSL.

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "protocolo": "PAI-EXEMPLO-001",
    "data_registro": "2026-09-21T10:00:00Z",
    "orgao_destinatario": "Ministério da Saúde",
    "origem_solicitacao": "Internet",
    "forma_resposta": "E-mail",
    "resumo_solicitacao": "Microdados de contratos de vacinação",
    "detalhamento_solicitacao": "Solicito notas fiscais e tabelas orçamentárias de 2020 a 2024.",
    "prazo_atendimento": "2026-10-11"
  }'
```

O exemplo retorna uma classificação `ALTO` pela regra heurística. O **[Guia para construir a solução do zero](docs/GUIA_REPRODUCAO.md)** explica o problema, a preparação dos dados e os passos para implementar uma solução semelhante em um projeto vazio.

Ao terminar, pare o serviço com:

```bash
docker compose down
```

## Documentação do projeto

- [`docs/GUIA_REPRODUCAO.md`](docs/GUIA_REPRODUCAO.md) — roteiro para entender o problema e construir uma solução semelhante do zero.
- [`docs/PRD.md`](docs/PRD.md) — requisitos e escopo do produto.
- [`docs/LAI_Entendimento_Negocio_v2.0.pdf`](docs/LAI_Entendimento_Negocio_v2.0.pdf) — contexto e entendimento de negócio da LAI.

## Uso de Inteligência Artificial

Foram utilizados agentes de IA do **OpenCode** e do **Antigravity** como apoio durante a execução do trabalho. Os agentes foram utilizados como escritores de código em pair programming com a equipe. Também foram utilizados para auxiliar na escolha do modelo de LLM utilizado no projeto, organizar e revisar a documentação, e estruturar um guia reproduzível de execução.

As respostas foram tratadas como sugestões, não como fonte definitiva. Todo código gerado por IA foi revisado e aprovado por uma pessoa da equipe antes de ser incorporado. A equipe também comparou as descrições com o código e os documentos do projeto, revisou comandos e exemplos e registrou divergências entre a implementação atual e especificações anteriores do PRD. As decisões de domínio, a validação do conteúdo e a responsabilidade pela entrega permanecem com a equipe.

Como artefato da implementação do projeto, temos o [PRD do Agente SIC-LAI](docs/PRD.md).

## Licença

Distribuído sob a licença [MIT](LICENSE).
