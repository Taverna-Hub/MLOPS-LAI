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

### Exemplos de predição

Os comandos `curl` abaixo são para Bash; no Windows, execute-os no Git Bash ou WSL. Também é possível enviar os mesmos JSONs pelo Swagger em [`http://localhost:8000/docs`](http://localhost:8000/docs).

O analisador sempre calcula um resultado heurístico. Ele o devolve diretamente para os casos específicos de risco `ALTO` e `BAIXO`, e para risco `MEDIO` quando o órgão contém “INSS”. Nos demais casos, tenta consultar a Qwen. Se a geração falhar ou não respeitar o contrato da resposta, usa o resultado heurístico como fallback. Assim, uma requisição pode consultar a Qwen sem que a resposta final tenha sido produzida por ela.

#### Exemplo 1 — Regra heurística, sem chamada à Qwen

O órgão e os termos do pedido correspondem à regra de risco alto.

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

Este exemplo retorna `ALTO` e score `0.88` pela regra heurística; a Qwen não é chamada para analisar esta requisição.

#### Exemplo 2 — Pedido aberto, consulta à Qwen

Este pedido não corresponde às regras específicas por texto ou órgão e segue para a inferência local da Qwen.

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "protocolo": "PAI-QWEN-01",
    "data_registro": "2026-10-12T11:00:00Z",
    "orgao_destinatario": "Instituto Brasileiro do Meio Ambiente e dos Recursos Naturais Renováveis (IBAMA)",
    "origem_solicitacao": "Internet",
    "forma_resposta": "E-mail",
    "resumo_solicitacao": "Etapas para autorização de visita técnica em unidade de conservação",
    "detalhamento_solicitacao": "Solicito informar quais documentos são necessários para pedir autorização de visita técnica a uma unidade de conservação federal, qual setor recebe o pedido e como o interessado pode acompanhar a análise."
  }'
```

Na execução de teste, a Qwen retornou `MEDIO`, score `0.8`, fatores explicativos e uma recomendação. A resposta gerada e a latência podem variar entre execuções; o score é indicativo, não uma probabilidade calibrada.

#### Exemplo 3 — Consulta à Qwen com fallback heurístico

Este pedido também não corresponde às regras específicas, então a aplicação tenta consultar a Qwen. Na execução de teste, a resposta gerada não respeitou o tipo esperado para os fatores de risco; a validação falhou e a API devolveu o fallback heurístico (`MEDIO`, score `0.50`).

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "protocolo": "PAI-QWEN-02",
    "data_registro": "2026-10-12T11:05:00Z",
    "orgao_destinatario": "Agência Nacional de Energia Elétrica (ANEEL)",
    "origem_solicitacao": "Internet",
    "forma_resposta": "E-mail",
    "resumo_solicitacao": "Critérios de fiscalização de medidores residenciais",
    "detalhamento_solicitacao": "Solicito os critérios utilizados para selecionar instalações residenciais para inspeção, o fluxo administrativo aplicado quando a inspeção identifica divergência e os prazos previstos para comunicar o resultado ao consumidor."
  }'
```

O campo `tempo_processamento_ms` inclui a duração da tentativa de inferência e varia conforme a máquina. O **[Guia para construir a solução do zero](docs/GUIA_REPRODUCAO.md)** explica o problema, a preparação dos dados e os passos para implementar uma solução semelhante em um projeto vazio.

Ao terminar, pare o serviço com:

```bash
docker compose down
```

## Documentação do projeto

- [`docs/GUIA_REPRODUCAO.md`](docs/GUIA_REPRODUCAO.md) — roteiro para entender o problema e construir uma solução semelhante do zero.
- [`docs/PRD.md`](docs/PRD.md) — requisitos e escopo do produto.
- [`docs/LAI_Entendimento_Negocio.pdf`](docs/LAI_Entendimento_Negocio.pdf) — contexto e entendimento de negócio da LAI.

## Uso de Inteligência Artificial

Foram utilizados agentes de IA do **OpenCode** e do **Antigravity** como apoio durante a execução do trabalho. Os agentes foram utilizados como escritores de código em pair programming com a equipe. Também foram utilizados para auxiliar na escolha do modelo de LLM utilizado no projeto, organizar e revisar a documentação, e estruturar um guia reproduzível de execução.

As respostas foram tratadas como sugestões, não como fonte definitiva. Todo código gerado por IA foi revisado e aprovado por uma pessoa da equipe antes de ser incorporado. A equipe também comparou as descrições com o código e os documentos do projeto, revisou comandos e exemplos e registrou divergências entre a implementação atual e especificações anteriores do PRD. As decisões de domínio, a validação do conteúdo e a responsabilidade pela entrega permanecem com a equipe.

Como artefato da implementação do projeto, temos o [PRD do Agente SIC-LAI](docs/PRD.md).

## Licença

Distribuído sob a licença [MIT](LICENSE).
