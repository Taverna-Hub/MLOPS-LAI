# Monitoramento do SIC-LAI

Esta entrega cobre a Parte 1 da atividade: rastro de entradas e saídas em arquivo texto append-only e `GET /metrics` compatível com Prometheus. A API continua usando regras específicas e, nos casos abertos, o OpenRouter. Uma resposta HTTP 200 pode ser um fallback.

## Demonstração somente com Docker

Na raiz do repositório, copie `.env.example` para `.env` e preencha `OPENROUTER_API_KEY`. Não é necessário instalar Python no host. A chave fica no ambiente do container, sem entrar na imagem.

```bash
docker compose up --build -d --wait
curl http://localhost:8000/health
curl http://localhost:8000/metrics
docker compose exec -T sic-lai-service /app/.venv/bin/python -m monitoring.generate_load
```

No PowerShell, use `curl.exe` em vez de `curl` quando este último for um alias de `Invoke-WebRequest`. Para copiar a configuração, use `Copy-Item .env.example .env`; em Bash, use `cp .env.example .env`.

A carga realiza **30 chamadas sequenciais** por rodada: 19 regras específicas, quatro abstenções, quatro rejeições com HTTP 422 e três pedidos que tentam o OpenRouter. Os exemplos são inteiramente fictícios e estão em `monitoring/cases.json`. Há variação de órgão, canal, forma de resposta e tamanho dos textos. `--rounds 2` repete a rodada, inclusive as três chamadas remotas; não há retry automático.

Acompanhe o rastro enquanto a carga roda, em outro terminal:

```bash
# Bash
tail -f logs/requests.jsonl
```

```powershell
# PowerShell
Get-Content -LiteralPath logs/requests.jsonl -Tail 5 -Wait
```

Os resultados e os snapshots de `/metrics` aparecem em `monitoring/generated/`, compartilhado com o container. Para analisar somente os identificadores daquela rodada:

```bash
docker compose exec -T sic-lai-service /app/.venv/bin/python -m monitoring.report --load-results monitoring/generated/load_results.json
```

O resultado fica em `monitoring/generated/report.json`. Confira `summary.sources.modelo_remoto` e `summary.sources.fallback`: o primeiro comprova resposta remota validada; o segundo identifica substituição pela heurística. Não deduza isso pelo status HTTP. Se houver rotação durante a rodada, inclua os arquivos anteriores explicitamente:

```bash
docker compose exec -T sic-lai-service /app/.venv/bin/python -m monitoring.report --log logs/requests.jsonl.5 logs/requests.jsonl.4 logs/requests.jsonl.3 logs/requests.jsonl.2 logs/requests.jsonl.1 logs/requests.jsonl --load-results monitoring/generated/load_results.json
```

Liste somente os arquivos existentes. O analisador identifica linhas inválidas, verifica a versão do registro, remove duplicações de `request_id` e avisa se faltarem eventos da rodada. Não reescreve os logs originais.

Fora do Docker, com Python 3.11+ e `uv`, os comandos equivalentes são:

```bash
uv sync --frozen --extra dev
uv run uvicorn src.app:app --host 0.0.0.0 --port 8000
# Em outro terminal:
uv run python -m monitoring.generate_load
uv run python -m monitoring.report --load-results monitoring/generated/load_results.json
```

## O que é registrado

Cada linha de `logs/requests.jsonl` é um objeto JSON completo, escrito após o atendimento. Dados operacionais aparecem também em atendimentos inválidos, erros internos e rotas desconhecidas. `/metrics` é excluído da coleta para que as consultas não gerem tráfego artificial. Rotas desconhecidas são agrupadas em `__unmatched__`.

O evento contém `schema_version`, `service_version`, timestamp UTC ISO 8601 com microssegundos, UUID interno, método, rota normalizada, status e desfecho. Respostas normais incluem o UUID no cabeçalho `X-Request-ID`. O UUID não vem do protocolo informado pelo cliente.

As medidas selecionadas são:

| ID | Registro JSONL | Série Prometheus, com prefixo `sic_lai_` |
| --- | --- | --- |
| M01 | `endpoint`, `method`, `status_code` | `http_requests_total{endpoint,method,status}` |
| M02 | `http_latency_ms` | `http_duration_seconds{endpoint,method}` |
| M03 | Derivada de `status_code` | Proporções calculadas com M01 |
| M05 | `analysis_ms` | `analysis_duration_seconds{source}` |
| M06 | `remote_latency_ms` | `openrouter_duration_seconds` |
| M07 | `result_source` | `results_total{source}` |
| M08 | `remote_error` quando há fallback | `fallbacks_total{reason}` |
| M09 | `schema_valid` | `remote_schema_total{result}` |
| M10 | `resumo_chars` | `input_summary_chars` |
| M11 | `detalhamento_chars` | `input_detail_chars` |
| M13 | `request_bytes` | `http_request_bytes{endpoint}` |
| M14 | `orgao_destinatario`, `origem_solicitacao`, `forma_resposta` | Frequências no JSONL/planilha; não são rótulos Prometheus livres |
| M15 | `score_risco` | `risk_score` |
| M16 | `nivel_risco` | `risk_levels_total{level}` |
| M17 | `fatores_count` | `risk_factors` |
| M19 | `prompt_tokens` | `openrouter_prompt_tokens` |
| M20 | `completion_tokens` | `openrouter_completion_tokens` |
| M21 | `reasoning_tokens` | `openrouter_reasoning_tokens` |
| M22 | `cost_usd` | `openrouter_cost_usd_total` |

Além dos contadores indicados por `_total`, as séries numéricas são histogramas e expõem `_bucket`, `_count` e `_sum`. Não há gauge de concorrência, contagem de palavras nem tamanho da recomendação: M04, M12 e M18 ficaram fora do escopo.

O log não contém protocolo, textos do pedido, textos das justificativas ou recomendação, corpos de erro do provedor, chave ou cabeçalhos de autenticação. Para entradas rejeitadas, as características não validadas ficam `null`, mas status, bytes recebidos e duração permanecem disponíveis. Só os campos previstos são registrados; campos extras do payload não são copiados.

`null` significa informação ausente ou não aplicável. Uma regra local não tem tokens, custo ou conformidade de schema remota; isso não equivale a zero consumo observado pelo provedor. Quando `usage.cost` vier como zero, o registro mantém `0`. Valores numéricos negativos, não finitos ou de tipo inesperado no `usage` ficam ausentes.

`result_source` assume `heuristica`, `modelo_remoto`, `fallback` ou `abstencao`. Motivos de fallback: `not_configured`, `http_error`, `timeout`, `network_error`, `invalid_output`, `incomplete_output` ou `unknown`. O status HTTP do provedor, quando recebido, fica em `remote_status_code`. Modelo solicitado, modelo servido e provedor são metadados separados.

## Por que essas variáveis

A escolha parte do [Entendimento do Negócio](../docs/LAI_Entendimento_Negocio.pdf) (CRISP-DM). A decisão apoiada é quais pedidos recém-registrados devem receber acompanhamento prioritário (seção 1.2), usando apenas informações disponíveis em t0 (seções 2.3 e 3.4). Cada grupo de variáveis responde a um ponto desse documento:

| Seção do Entendimento do Negócio | O que diz | Variáveis registradas |
| --- | --- | --- |
| 3.4 e 3.6 — entradas candidatas em t0 | Órgão, forma de resposta, origem e texto do pedido estão disponíveis no registro | `orgao_destinatario`, `origem_solicitacao`, `forma_resposta`, `resumo_chars`, `detalhamento_chars`, `request_bytes` |
| 2.3 — restrições | Identificadores pessoais e dados demográficos não são usados | O texto do pedido e o protocolo não são gravados; apenas os tamanhos |
| 2.5 — diferenças entre órgãos | Padrões podem variar entre órgãos destinatários | `orgao_destinatario` permite segmentar distribuições e comparações de drift |
| 2.5 — saturação operacional | Uma fila de alertas maior que a capacidade da equipe torna a indicação pouco útil | `nivel_risco` e `score_risco`: a proporção de `ALTO` mede o volume de pedidos sinalizados como prioritários |
| 2.5 — vazamento temporal | Campos posteriores a t0 devem ser bloqueados | `status_code` 422 e `outcome="validation_error"` contam tentativas rejeitadas |
| 3.7 — regra de abstenção | Sem dados essenciais, o sistema não deve preencher lacunas por suposição | `result_source="abstencao"` e `nivel_risco="INDETERMINADO"` |
| 3.7 — indicação de risco, não certeza | O resultado apoia uma decisão humana | `fatores_count`, `result_source`: distinguem regra, modelo e fallback por trás de cada indicação |
| 2.2 — dependências de implantação | Operação ainda não definida | Latências, `remote_error`, `schema_valid`, tokens e custo separam mudança na demanda de indisponibilidade do modelo remoto |

`data_registro` também é candidata em t0 (seção 3.4), e a seção 3.6 sugere características derivadas dela, como hora e dia da semana. Nesta versão, ela não é registrada: os casos de demonstração usam a mesma data, de modo que essas variáveis seriam constantes. É a primeira inclusão prevista para uma próxima versão do registro (`schema_version` 2).

Distribuições de scores devem ser separadas por origem: as regras usam scores fixos e o modelo gera valores indicativos. Abstenção usa score zero. Nenhum desses valores é probabilidade calibrada. Não há rótulos de atrasos reais para medir acurácia, precisão ou recall (seção 3.7).

### Conjunto de referência para KS e PSI

Não há conjunto de treinamento: as regras e o modelo remoto não foram ajustados com dados históricos. Por isso, definimos manualmente como **referência** o arquivo [`examples/requests.jsonl`](examples/requests.jsonl), a rodada de 16/11/2026 com 30 pedidos fictícios. Os registros novos em `logs/requests.jsonl` são a amostra a comparar com ela.

Ao usar essa referência, considere:

- **Tamanho.** São 30 registros, dos quais 26 com HTTP 200 e somente 3 respostas do modelo remoto. KS funciona com amostras pequenas, mas perde poder. PSI costuma exigir centenas de observações por período para que as faixas não fiquem vazias.
- **Variação.** `--rounds N` repete os mesmos casos. Isso aumenta o volume de latências e tokens, mas não muda a distribuição das entradas; não use rodadas repetidas para simular drift de entrada.
- **Tipo de variável.** KS se aplica às numéricas contínuas (`resumo_chars`, `detalhamento_chars`, `request_bytes`, latências, tokens). `score_risco` das regras assume poucos valores fixos; trate-o como categórico em PSI, ou compare apenas os scores de `modelo_remoto`. Categorias (`orgao_destinatario`, `nivel_risco`, `result_source`) entram no PSI por frequência.

A referência é demonstrativa, não um retrato da operação real. Em produção, ela deverá ser substituída por uma amostra de pedidos reais (por exemplo, da base pública da CGU citada na seção 2.2), validada com o SIC. Nesta entrega somente coletamos os dados: não executamos KS, PSI ou testes de drift conceitual.

## Como interpretar `/metrics`

A exposição usa `# HELP`, `# TYPE`, nomes de séries, rótulos e valores numéricos. Durações estão em **segundos** nas métricas e **milissegundos** no JSONL. O tempo HTTP é medido na aplicação ASGI: inclui validação, análise e envio da resposta ao servidor, sem incluir a rede até o cliente nem a escrita posterior do log. O tempo remoto mede a operação de rede; a análise também inclui montagem de mensagens e validação do resultado.

### Contadores e taxas de erros

Para um mesmo endpoint e intervalo, use:

```text
taxa_4xx = quantidade de respostas 400–499 / total de respostas
taxa_5xx = quantidade de respostas 500–599 / total de respostas
```

Se o total for zero, a taxa é indisponível, não zero. Um único snapshot mostra acumulados desde o início do processo. Para um intervalo, subtraia dois snapshots do mesmo processo. Se o processo reiniciou, não subtraia os contadores atravessando o reset. Guarde as duas exposições, como faz o gerador de carga.

Com um servidor Prometheus externo, uma consulta equivalente para a janela de cinco minutos seria:

```promql
sum(increase(sic_lai_http_requests_total{endpoint="/predict",status=~"4.."}[5m]))
/
sum(increase(sic_lai_http_requests_total{endpoint="/predict"}[5m]))
```

Troque `4..` por `5..` para falhas do servidor. A instalação de Prometheus não é necessária para esta atividade. Separe taxa HTTP de fallback: uma falha remota pode produzir HTTP 200 por meio da heurística.

### Conformidade do schema

```text
conformidade = remote_schema_total{result="valid"}
            / (remote_schema_total{result="valid"} + remote_schema_total{result="invalid"})
```

O denominador inclui somente respostas HTTP 2xx recebidas do OpenRouter. JSON inválido, contrato incompatível e geração incompleta entram como inválidos. Ausência de chave, timeout e erro HTTP não entram nesse denominador. Os metadados de uso disponíveis são preservados mesmo quando o conteúdo gerado é rejeitado.

### Histograma de latência

Os buckets são **cumulativos**. `le="1"` conta tudo que levou até um segundo; `le="5"` inclui esses atendimentos e os de até cinco segundos. A frequência da faixa `(1, 5]` é `bucket_5 - bucket_1`. O primeiro bucket já é a frequência da primeira faixa. A última faixa usa o bucket `+Inf` menos o anterior.

Exemplo demonstrativo:

| Limite em segundos | Acumulado | Frequência da faixa |
| --- | ---: | ---: |
| 0,1 | 8 | 8 |
| 1 | 10 | 2 |
| 10 | 13 | 3 |
| +Inf | 14 | 1 |

Os limites reais de latência são `0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300, +Inf`. A média é `_sum / _count` quando há observações. Buckets também permitem estimar percentis, mas não recuperam as observações individuais.

Na planilha, os histogramas são calculados a partir das observações do JSONL, com faixas rotuladas. As faixas têm larguras diferentes e o eixo horizontal é categórico: as barras mostram frequência por faixa, não densidade de probabilidade. As mesmas observações permitem histogramas de resumo, detalhamento, bytes, score, fatores e tokens.

### Boxplot e percentis

Use as latências individuais do JSONL, separadas pelo endpoint desejado. A planilha apresenta estatísticas por endpoint e por variável:

1. Ordenar as observações numéricas; ignorar ausências e manter zeros reais.
2. Calcular Q1, mediana e Q3 com percentis inclusivos de 25%, 50% e 75%.
3. Calcular `IQR = Q3 - Q1`.
4. Definir os limites `Q1 - 1,5 × IQR` e `Q3 + 1,5 × IQR`.
5. Os bigodes terminam no menor e no maior valor **observado** dentro desses limites.
6. Os valores fora dos limites são outliers. Outlier estatístico não significa falha operacional.

No Excel, use `PERCENTILE.INC(intervalo,0.25)`, `MEDIAN(intervalo)` e `PERCENTILE.INC(intervalo,0.75)`. Para P95, use `PERCENTILE.INC(intervalo,0.95)`. O analisador Python implementa a mesma interpolação inclusiva. Nomes de funções e separadores podem aparecer traduzidos pelo Excel.

O boxplot da planilha representa as latências HTTP do conjunto e mantém os outliers em tabela separada, para permitir leitura da caixa sem ocultar os valores extremos. Para comparar endpoints, consulte suas linhas na aba `Distribuicoes`. Os histogramas Prometheus não permitem reconstruir um boxplot exato; por isso mantemos as observações individuais.

## Tokens e custo

Tokens de geração já incluem o raciocínio quando assim informados pelo provedor. Portanto, não calcule total como entrada + geração + raciocínio. O total é entrada + geração; raciocínio é uma parcela informativa da geração. Os campos podem não existir em algumas respostas.

O custo vem de `usage.cost`, em USD. O exemplo gratuito informa zero; registramos o valor efetivamente retornado. O contador de custo pode permanecer em zero tanto sem chamadas quanto com chamadas gratuitas: confira também as contagens de observações de tokens e os registros individuais.

## Retenção e execução

| Informação | Duração |
| --- | --- |
| Métricas em `/metrics` | Acumuladas na memória do processo; reiniciam ao recriá-lo |
| `logs/requests.jsonl` | Arquivo ativo, acrescido por novos eventos |
| `requests.jsonl.1` a `.5` | Cinco arquivos anteriores; `.1` é o mais recente |
| `monitoring/generated/` | Snapshots e relatórios preservados no host até remoção manual |

A rotação ocorre antes de uma nova linha atingir o limite configurado de **10.000.000 bytes UTF-8**, sem dividir o JSON. Uma linha excepcionalmente maior que o limite é mantida inteira, podendo ultrapassá-lo. Arquivos anteriores não são editados; na rotação, são renomeados e o mais antigo é excluído. O espaço típico é de até aproximadamente 60 MB, incluindo o ativo. Isso é retenção por tamanho, não por número de dias.

`MONITORING_LOG_PATH`, `MONITORING_MAX_BYTES` e `MONITORING_BACKUPS` configuram o arquivo, o limite e a quantidade de arquivos anteriores. No Compose, o caminho interno é `/app/logs/requests.jsonl`, vinculado a `./logs` no host. Recriar o container preserva esses arquivos. O diretório de relatórios também é vinculado ao host. Os diretórios gerados são ignorados pelo Git.

A execução suportada usa **um processo Uvicorn**. Não use múltiplos workers ou dois servidores escrevendo no mesmo arquivo: o handler não coordena rotação entre processos. Falta de permissão ao abrir o log impede a inicialização; falhas posteriores do handler são reportadas no stderr. As métricas não são reconstruídas a partir do arquivo após reinício.

## Planilha e evidência versionada

Abra [`examples/monitoramento.xlsx`](examples/monitoramento.xlsx). Ela contém:

- `Resumo`: contagens, taxas, consumo, histogramas e boxplot.
- `Distribuicoes`: contagem, média, extremos, quartis, P95, limites, bigodes e outliers de cada variável e endpoint.
- `Dados`: observações individuais; timestamps são exibidos em UTC.
- `Dicionario`: as 19 métricas e as frequências de categorias de entrada e saída.

`examples/requests.jsonl`, `report.json`, `load_results.json` e `metrics_before.prom`/`metrics_after.prom` documentam uma rodada real de **30 pedidos fictícios em 16/11/2026**: 19 resultados heurísticos, quatro abstenções, quatro rejeições HTTP 422 e três respostas remotas válidas. O custo informado foi zero. Os tempos refletem aquela execução, não uma garantia de desempenho.

As fórmulas e os gráficos da planilha estão vinculados às células. O boxplot usa segmentos de dispersão com referências aos quartis e bigodes. Outliers aparecem em tabela separada. Os cálculos da planilha foram comparados com o relatório Python, incluindo a distinção entre ausência, zero e schema inválido.

A planilha é um exemplo estático da rodada acima. Para analisar uma nova rodada, use o `report.json` gerado pelo `monitoring.report`, que traz as mesmas estatísticas, ou cole as novas observações do JSONL na aba `Dados`, estendendo os intervalos das fórmulas.

## Verificação da entrega

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run ruff format src monitoring tests --check
docker compose config --quiet
```

Os testes simulam respostas e erros remotos sem consumir a cota do OpenRouter. Cobrem append-only, UTF-8, rotação, reinício, concorrência, ausência de textos/segredos, todas as origens de resultado, schema inválido, reconciliação de métricas, exemplos e estrutura do `.xlsx`.

Consulte [`VALIDACAO.md`](VALIDACAO.md) para a checagem final item a item após releitura do enunciado.

## Referências

- [Logging em Python](https://docs.python.org/pt-br/3/howto/logging.html)
- [Formato de exposição Prometheus](https://prometheus.io/docs/instrumenting/exposition_formats/)
- [Histogramas no cliente Python do Prometheus](https://prometheus.github.io/client_python/instrumenting/histogram/)
