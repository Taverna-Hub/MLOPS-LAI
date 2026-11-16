# Checagem final da atividade

A atividade se divide em duas partes: uma para quem serve o modelo com BentoML ou FastAPI e outra para quem usa GitHub Actions. Como o nosso serviço roda em FastAPI, seguimos a Parte 1. A tabela abaixo relaciona cada item pedido com o que foi implementado e onde está a evidência.

## Conferência dos requisitos

| Exigência | Implementação e evidência | Resultado |
| --- | --- | --- |
| Reutilizar um serviço de inferência | `/predict` preserva o contrato anterior e consulta o modelo remoto nos casos abertos | Verificado |
| Professor gera carga somente seguindo o README | README principal aponta os comandos Docker, geração de carga e acompanhamento do arquivo; guia detalhado em `monitoring/README.md` | Verificado no Docker |
| Arquivo texto append-only no disco do processo | JSONL UTF-8; um evento por atendimento; testes verificam que o prefixo anterior não muda | Verificado |
| Rastro do que entra e sai | Medidas de tamanho, categorias de entrada, score, nível, número de fatores e origem do resultado; sem textos completos nem protocolo, conforme a restrição de dados pessoais da seção 2.3 do Entendimento do Negócio | Verificado |
| Dados para histogramas de entrada e saída | Resumo/detalhamento/bytes de entrada; score/fatores e uso da geração; valores individuais no JSONL | Verificado |
| Dados para boxplots de entrada e saída | Observações individuais e estatísticas inclusivas para todas as variáveis numéricas disponíveis | Verificado |
| Preparação para futuras comparações KS/PSI | Dados numéricos/categóricos, schema versionado, origem do resultado e timestamps; `examples/requests.jsonl` definido manualmente como conjunto de referência, com limites de tamanho e variação documentados | Verificado; análises futuras fora desta entrega |
| Escolha de variáveis justificada pelo negócio (CRISP-DM) | Guia relaciona cada grupo de variáveis a uma seção de `docs/LAI_Entendimento_Negocio.pdf` (entradas em t0, restrições, riscos, abstenção); não apresenta score como probabilidade calibrada | Documentado |
| Data e hora detalhadas | UTC ISO 8601 com seis casas decimais no JSONL | Verificado |
| Rotação permitida sem reescrever eventos | Limite de 10.000.000 bytes, arquivo ativo e cinco anteriores; descarte automático do mais antigo | Testes de UTF-8, CRLF/LF e retenção aprovados |
| `GET /metrics` no servidor | Exposição via cliente Python Prometheus, na mesma porta da API | Verificado no Docker e por parser Prometheus |
| Compatibilidade de formato | Séries com HELP, TYPE, contadores e histogramas; snapshots `.prom` versionados | Verificado |
| Texto explicando `/metrics` | Guia com nomes, unidades, acumulados, diferenças entre snapshots e resets | Documentado |
| Histograma de latência por endpoint | Buckets cumulativos, cálculo por diferença e dados individuais; planilha com gráfico de frequências | Verificado |
| Boxplot de latência por endpoint | Quartis, IQR, limites, bigodes e outliers; tabela por endpoint, gráfico do conjunto e valores extremos separados | Verificado |
| Taxa de erros | 4xx e 5xx separados; denominador comum; taxa indisponível quando total é zero | Verificado |
| Explicar tempo de preservação | Métricas em memória por processo; arquivos por tamanho; snapshots e relatórios até remoção manual | Documentado e validado por recriação do container |
| Planilha preferencial | `.xlsx` com fórmulas, distribuições, categorias, histogramas e boxplot; dados reais de pedidos fictícios | Exportado, reaberto e revisado visualmente |

## Validações executadas

- **31 testes automatizados**, incluindo os 13 testes anteriores da integração OpenRouter. Transporte simulado nos testes: sem consumo de cota.
- `uv run ruff check .`, formatação de `src`, `monitoring` e `tests`, `uv lock --check --offline` e `docker compose config --quiet` aprovados.
- Build da imagem Linux com Python 3.11 e execução pelo Compose; container com healthcheck saudável.
- Rodada real fora do Docker: **30 atendimentos, 19 resultados heurísticos, quatro abstenções, quatro rejeições 422 e três respostas remotas válidas**. Os registros, snapshots e planilha dessa rodada estão em `monitoring/examples/`.
- Rodada real dentro do Docker com os mesmos totais, sem divergências HTTP. O relatório foi gerado pelo módulo Python dentro do container e apareceu no diretório compartilhado do host.
- As duas rodadas somaram **seis chamadas reais ao OpenRouter**, todas com resposta válida para o contrato e custo informado zero. Não houve fallback nessas seis chamadas.
- Antes de recriar o container, foi guardada uma cópia dos bytes do arquivo. Depois da recriação, o arquivo preservou integralmente o prefixo anterior, os contadores de `/predict` estavam reiniciados e um novo evento foi acrescentado e contabilizado.
- Foi verificado que a imagem não contém `.env` nem o runtime Torch.
- Os cálculos do `.xlsx` foram comparados com o relatório Python. Alterações temporárias de latência, custo ausente/zero e schema ausente/inválido confirmaram o recálculo; os dados originais foram restaurados antes de exportar.
- O `.xlsx` exportado foi reaberto para conferir a renderização do gráfico de dispersão que representa a caixa e os bigodes. Testes verificam fórmulas, caches, quatro gráficos e referências às células.

## Decisões e limites mantidos

- As 19 métricas escolhidas foram implementadas. M04, M12 e M18 permanecem excluídas.
- Sem protocolo, textos completos, chave ou corpos de erro no JSONL. UUID interno para correlação.
- M14 fica no log e na planilha, sem transformar nomes livres de órgãos/canais em rótulos Prometheus.
- Ausência é `null`, não zero. Raciocínio não é somado novamente à geração. Erros HTTP remotos não entram na taxa de conformidade de schema.
- Dados de exemplo são fictícios; as latências são medições reais de demonstração e não caracterizam um SLA nem uma avaliação de acurácia.
- Execução suportada com um processo Uvicorn. Não há coordenação de rotação entre múltiplos processos.
- Não há servidor Prometheus, alertas, KS/PSI, treinamento ou avaliação com desfechos históricos nesta entrega.
- Características derivadas de `data_registro` (hora, dia da semana), candidatas em t0 pela seção 3.6 do Entendimento do Negócio, ficam para a próxima versão do registro: os casos de demonstração usam uma única data.
- A planilha é um exemplo estático da rodada versionada; novas rodadas são analisadas pelo `report.json`. Não foi testada edição no aplicativo Excel desktop.

## Versionamento

Cada feature recebeu commit no padrão Conventional Commits. `.env`, logs locais e relatórios gerados ficam fora dos commits.
