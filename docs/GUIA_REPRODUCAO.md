# Guia para construir a solução do zero — Agente SIC-LAI

Este roteiro ajuda uma pessoa desenvolvedora júnior a entender o problema e construir uma solução semelhante em um **diretório vazio**. Não é um passo a passo para clonar e executar este repositório; o caminho de execução do projeto pronto está no [README](../README.md).

O trabalho tem três partes diferentes: entender e validar as regras do negócio, analisar dados históricos sem vazamento temporal e implementar um serviço de inferência. A implementação atual cobre o serviço, mas não inclui uma pipeline de treinamento com a base histórica.

## 1. Comece pela decisão de negócio

A Lei de Acesso à Informação (LAI) garante o acesso a informações públicas. O Serviço de Informação ao Cidadão (SIC) recebe, encaminha e acompanha cada Pedido de Acesso à Informação (PAI). O problema considerado é que a equipe pode perceber tarde demais que um pedido corre risco de ultrapassar o prazo aplicável.

Formule a decisão que o sistema deve apoiar:

> Para cada pedido recém-registrado, o servidor do SIC deve decidir se ele merece acompanhamento prioritário antes do vencimento do prazo.

Isso define o escopo:

- **Usuário e decisor:** servidor do SIC; a decisão permanece humana.
- **Unidade de análise:** um pedido individual, não o cidadão ou o órgão inteiro.
- **Momento da análise:** t0, logo após o registro e a triagem inicial disponível.
- **Objetivo:** indicar risco e fornecer fatores que ajudem a priorizar o acompanhamento.
- **Fora do escopo:** responder ao cidadão, conceder/negar acesso, avaliar o mérito da resposta ou determinar sanções.

Leia o [Entendimento de Negócio da LAI](LAI_Entendimento_Negocio_v2.0.pdf) e o [PRD](PRD.md). O processo atual de priorização, a capacidade diária da equipe e metas de sucesso ainda não estão definidos nos documentos; registre essas questões como pendências para validação com usuários e responsáveis de negócio.

## 2. Defina t0 e evite data leakage

Antes de usar um campo como entrada, pergunte: **esse valor está disponível e estável no instante em que o servidor precisa tomar a decisão?** Um campo preenchido mais tarde pode revelar o próprio desfecho e invalidar a avaliação.

| Grupo | Campos | Tratamento inicial |
| --- | --- | --- |
| Candidatos a entrada em t0 | `DataRegistro`, `OrgaoDestinatario`, `FormaResposta`, `OrigemSolicitacao`, `ResumoSolicitacao`, `DetalhamentoSolicitacao` | Verificar presença, qualidade e momento de preenchimento. |
| Disponibilidade a confirmar | `PrazoAtendimento`, `AssuntoPedido`, `SubAssuntoPedido`, `Tag` | Não usar sem validar com o SIC e o responsável pelos dados. |
| Não usar como entrada nesta versão | `DataResposta`, `Decisao`, `EspecificacaoDecisao`, estado final de `Situacao`, `FoiProrrogado`, `FoiReencaminhado` | Podem ser eventos posteriores ao instante de decisão. |

O desfecho histórico proposto é `pedido_atrasado`:

- `ATRASADO` se `DataResposta` for posterior a `PrazoAtendimento`;
- `NO_PRAZO` se a resposta ocorrer até `PrazoAtendimento`;
- sem rótulo se as datas estiverem ausentes ou inconsistentes.

Essa regra é provisória: confirme se `PrazoAtendimento` representa o prazo final aplicável, inclusive após prorrogações e reencaminhamentos. Um pedido ainda sem resposta não deve ser rotulado automaticamente como `NO_PRAZO`; pode estar em andamento ou fora da janela de observação.

## 3. Monte um projeto vazio

Os comandos a seguir usam Bash (Linux, macOS, WSL ou Git Bash), Python 3.11+ e `uv`:

```bash
mkdir sic-lai
cd sic-lai
uv init --python 3.11
mkdir -p src/agent src/models tests data/raw data/processed
uv add pandas scikit-learn
uv add fastapi "uvicorn[standard]" pydantic pydantic-settings transformers torch accelerate
uv add --dev pytest httpx ruff
```

`pandas` e `scikit-learn` servem à exploração e a eventuais experimentos supervisionados. O serviço atual não carrega esses componentes para inferência. Gere e versione `uv.lock`; ignore `.venv/`, `.env`, caches, `data/raw/` e `data/processed/`. Crie `.env.example` somente com nomes de variáveis opcionais, sem credenciais ou valores sensíveis.

Uma estrutura inicial possível:

```text
sic-lai/
├── data/
│   ├── raw/                # origem local, não versionada
│   └── processed/          # resultados locais, não versionados
├── src/
│   ├── app.py              # rotas FastAPI
│   ├── config.py           # configurações de ambiente
│   ├── schemas.py          # contratos e proteção temporal
│   ├── agent/
│   │   ├── analyzer.py     # abstenção, heurísticas, SLM e fallback
│   │   └── prompt.py       # instruções para saída estruturada
│   └── models/
│       └── loader.py       # carregamento singleton do modelo
└── tests/
```

## 4. Localize e explore os dados

A fonte é a [área oficial de Dados Abertos LAI/Fala.BR da CGU](https://falabr.cgu.gov.br/web/dadosabertoslai). O [guia oficial de download e dicionário](https://www.gov.br/acessoainformacao/pt-br/falabr/visao-geral/busca-de-pedidos-e-respostas-download-de-dados/busca-de-pedidos-e-respostas-download-de-dados) descreve os campos e os arquivos. Há arquivos estruturados e arquivos filtrados que incluem texto dos pedidos; para avaliar texto, selecione uma versão que contenha `DetalhamentoSolicitacao` e consulte o dicionário correspondente.

Os CSVs filtrados seguem o padrão `Arquivos_csv_<ANO>.zip`. O link abaixo exemplifica um ano; confirme no portal a disponibilidade do período que deseja estudar:

```text
https://dadosabertos-download.cgu.gov.br/FalaBR/Arquivos_FalaBR_Filtrado/Arquivos_csv_2023.zip
```

Em Bash, baixe e inspecione o arquivo antes de descompactá-lo. Para outro ano, atualize o ano na URL e no nome do arquivo:

```bash
mkdir -p data/raw/lai-2023
curl --fail --location \
  --output data/raw/Arquivos_csv_2023.zip \
  https://dadosabertos-download.cgu.gov.br/FalaBR/Arquivos_FalaBR_Filtrado/Arquivos_csv_2023.zip
unzip -l data/raw/Arquivos_csv_2023.zip
unzip -o data/raw/Arquivos_csv_2023.zip -d data/raw/lai-2023
```

Registre a URL, a data da extração, os anos utilizados, a versão do dicionário e os filtros aplicados. Mantenha os dados originais em `data/raw/` e não os envie ao Git. Os arquivos podem incluir identificadores, tabelas de solicitantes e texto livre: use somente campos necessários, revise o conteúdo mesmo quando a base for filtrada e não publique dados ou exemplos reais.

O tutorial oficial descreve CSV separado por `;` e codificado em `utf-16`; confirme essas características para cada arquivo. Depois de baixar e descompactar uma amostra em `data/raw/`, use Pandas para inspecionar o schema:

```python
from pathlib import Path

import pandas as pd

arquivo = next(Path("data/raw").rglob("*Pedidos*.csv"))
pedidos = pd.read_csv(arquivo, sep=";", encoding="utf-16", low_memory=False)

print(pedidos.shape)
print(pedidos.columns.tolist())
print(pedidos[["DataRegistro", "PrazoAtendimento", "DataResposta"]].isna().mean())
print(pedidos["OrgaoDestinatario"].value_counts().head(10))
```

Verifique duplicatas, datas impossíveis, colunas ausentes, variações de schema entre anos, variações nos nomes dos órgãos e qualidade do texto. Normalize nomes e formatos em passos registrados; não descarte linhas silenciosamente. Exclua identificadores e informações demográficas dos preditores desta decisão.

Os nomes publicados pela CGU aparecem em CamelCase (por exemplo, `DataRegistro`); converta-os explicitamente para os nomes do contrato da API (por exemplo, `data_registro`) em uma fronteira documentada da pipeline.

## 5. Crie o target e avalie um baseline

Converta as datas com o formato definido pelo dicionário e rotule somente respostas observáveis:

```python
for coluna in ["DataRegistro", "PrazoAtendimento", "DataResposta"]:
    pedidos[coluna] = pd.to_datetime(
        pedidos[coluna], dayfirst=True, errors="coerce"
    )

rotulaveis = pedidos.dropna(subset=["DataResposta", "PrazoAtendimento"]).copy()
rotulaveis["pedido_atrasado"] = (
    rotulaveis["DataResposta"] > rotulaveis["PrazoAtendimento"]
).astype("int8")
```

Esse trecho implementa a hipótese de target documentada; ele não resolve a pendência sobre o prazo aplicável. Conte as classes, examine os registros excluídos e valide amostras com o dicionário e um especialista antes de treinar.

Se fizer uma experiência supervisionada, separe treino, validação e teste **por tempo de registro**: períodos antigos para treino e períodos posteriores para avaliação. Evite divisão aleatória entre anos, que pode tornar a avaliação pouco representativa de pedidos futuros. Compare com um baseline simples e avalie precisão e recall da classe atrasada, curva precision-recall e calibração. A acurácia isolada não representa os custos diferentes de falsos positivos e falsos negativos.

Defina o volume de alertas aceitável e os limites de métricas com o SIC. O entendimento de negócio não define baseline operacional, meta quantitativa nem capacidade de acompanhamento; esses valores não devem ser inventados pelo time técnico.

## 6. Escolha uma arquitetura para o escopo

O caminho recomendado em aula foi **BentoML** para servir, **Google ADK** para agentes e **GitHub Actions** para automação quando necessário. Outras pilhas são permitidas. O projeto existente escolheu **FastAPI**, **Transformers** e Docker Compose: é um fluxo curto de validação, regras e uma inferência local, sem chamadas a ferramentas ou orquestração multiagente. Por isso ele não utiliza BentoML nem Google ADK. Atualmente também não há workflow de GitHub Actions.

O PRD registra uma proposta anterior e cita Qwen 1.5B em algumas partes; a implementação atual usa Qwen 0.5B. Use README e código-fonte para conferir o comportamento entregue, e trate o PRD como referência de requisitos, considerando essa divergência técnica.

Para reproduzir o serviço atual, implemente o fluxo:

1. Validar o payload e bloquear campos posteriores a t0.
2. Abster-se quando os dados mínimos forem insuficientes.
3. Aplicar heurísticas determinísticas nos padrões conhecidos.
4. Para casos abertos, montar um prompt e chamar o SLM local `Qwen/Qwen2.5-0.5B-Instruct`.
5. Interpretar e validar o JSON da geração; usar fallback heurístico quando houver falha.
6. Entregar a recomendação ao servidor do SIC, sem decisão automática.

O Qwen é distribuído no [Hugging Face](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct), sob licença Apache 2.0. Fixe dependências no `uv.lock`; para reproduzir também os pesos, registre a revisão específica do modelo utilizada.

> **Limite da implementação existente:** ela não foi treinada com a base histórica descrita acima. As heurísticas usam scores definidos em código, e o SLM gera uma resposta estruturada a partir do prompt. Portanto, o score atual é indicativo, não uma probabilidade calibrada nem a saída de um classificador supervisionado. A experiência de treino e avaliação é uma etapa analítica adicional.

## 7. Implemente contrato, analisador e API

### Contrato e proteção temporal

Defina como campos obrigatórios protocolo, data de registro, órgão destinatário, origem, forma de resposta, resumo e detalhamento. Mantenha `PrazoAtendimento` opcional até confirmar sua disponibilidade operacional em t0.

Antes da validação normal do schema, examine o payload bruto e rejeite `DataResposta`, `Decisao`, `EspecificacaoDecisao`, estado final de `Situacao`, `FoiProrrogado` e `FoiReencaminhado` (ou os nomes normalizados usados na API). Retorne HTTP 422 com indicação do campo e da violação temporal. Campos extras desconhecidos não devem se tornar preditores implicitamente.

### Abstenção e resposta

Se o órgão ou o detalhamento estiver vazio, ou o texto for insuficiente, retorne `INDETERMINADO`, score `0.0`, justificativa e recomendação de pedir esclarecimento. Para demais casos, responda com protocolo, nível (`ALTO`, `MEDIO`, `BAIXO` ou `INDETERMINADO`), score entre 0 e 1, fatores, recomendação e latência.

### Orquestração de heurística e SLM

Separe o analisador em etapas explícitas:

```text
payload -> validação t0 -> abstenção?
        -> regra conhecida? -> resultado heurístico
        -> caso aberto -> prompt -> SLM local -> parse/validação JSON
        -> erro de inferência ou parse -> fallback heurístico
```

As regras atuais cobrem padrões demonstrativos: pedidos extensos/históricos tendem a alto risco; documentos ostensivos, a baixo; extrações operacionais moderadas, a médio; os demais casos usam uma regra padrão. Justifique cada regra, não trate associação com um órgão como evidência suficiente e escreva um teste para cada caminho.

Carregue tokenizer e modelo uma única vez em CPU. O prompt deve incluir apenas os campos permitidos em t0 e solicitar JSON. Trate a geração do LLM como entrada não confiável: extraia e valide o JSON, nível, score e tipos antes de compor a resposta.

### Endpoints e documentação viva

Implemente `GET /health` e `POST /predict`. O endpoint de predição recebe o schema do pedido e retorna o schema de triagem. Documente os contratos via OpenAPI e mantenha exemplos de requisição e resposta no README. Um `/health` que só repete a configuração não comprova que o modelo foi carregado; deixe essa semântica clara ou implemente uma verificação real de prontidão.

## 8. Teste, empacote e automatize

Crie testes que não dependam de baixar o Qwen: substitua o pipeline por um objeto de teste. Cubra pelo menos:

1. Caso complexo classificado como risco alto.
2. Pedido simples de informação pública classificado como risco baixo.
3. Demanda operacional moderada.
4. Campo posterior a t0 rejeitado com HTTP 422.
5. Detalhamento insuficiente retornando `INDETERMINADO`.
6. Falha do SLM ou JSON inválido acionando o fallback.

Rode `uv run pytest` e `uv run ruff check .`. Se usar integração contínua, configure GitHub Actions para executar essas verificações. Para Docker, cacheie os pesos durante o build, exponha a porta da API e não exija chave de um serviço externo.

## 9. Compare com a implementação deste repositório

Use os módulos existentes para comparar a solução independente com a entregue:

| Responsabilidade | Arquivo atual |
| --- | --- |
| Endpoints `/health` e `/predict` | `src/app.py` |
| Schema e campos bloqueados | `src/schemas.py` |
| Heurísticas, chamada ao SLM e fallback | `src/agent/analyzer.py` |
| Prompt | `src/agent/prompt.py` |
| Carregamento do Qwen | `src/models/loader.py` |
| Configuração | `src/config.py` |

O serviço existente não contém a extração/preparação da base histórica nem o treinamento ou a avaliação de um classificador. Distinguir isso do estudo de dados é parte da reprodução correta do projeto.
