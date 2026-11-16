"""Agregações Prometheus das observações JSONL selecionadas para a atividade."""

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

LATENCY_BUCKETS = (0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300)
SIZE_BUCKETS = (0, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000)
TOKEN_BUCKETS = (0, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
SOURCES = ("heuristica", "modelo_remoto", "fallback", "abstencao")
ERRORS = (
    "not_configured",
    "http_error",
    "timeout",
    "network_error",
    "invalid_output",
    "incomplete_output",
    "unknown",
)


class Metrics:
    def __init__(self):
        self.registry = CollectorRegistry()

        def counter(name, description, labels=()):
            return Counter("sic_lai_" + name, description, labels, registry=self.registry)

        def histogram(name, description, buckets, labels=()):
            return Histogram(
                "sic_lai_" + name, description, labels, buckets=buckets, registry=self.registry
            )

        self.requests = counter(
            "http_requests_total", "Atendimentos HTTP concluídos", ("endpoint", "method", "status")
        )
        self.http_time = histogram(
            "http_duration_seconds",
            "Latência HTTP completa",
            LATENCY_BUCKETS,
            ("endpoint", "method"),
        )
        self.request_size = histogram(
            "http_request_bytes",
            "Bytes do corpo efetivamente recebido",
            (0, 256, 512, 1024, 4096, 16384, 65536, 262144, 1048576),
            ("endpoint",),
        )
        self.analysis = histogram(
            "analysis_duration_seconds", "Tempo de análise", LATENCY_BUCKETS, ("source",)
        )
        self.remote_time = histogram(
            "openrouter_duration_seconds",
            "Tempo de uma tentativa de rede OpenRouter",
            LATENCY_BUCKETS,
        )
        self.sources = counter("results_total", "Origem do resultado de predição", ("source",))
        self.fallback = counter("fallbacks_total", "Fallbacks por motivo", ("reason",))
        self.schema = counter(
            "remote_schema_total", "Respostas HTTP 2xx por conformidade ao contrato", ("result",)
        )
        for source in SOURCES:
            self.sources.labels(source).inc(0)
        for reason in ERRORS:
            self.fallback.labels(reason).inc(0)
        for result in ("valid", "invalid"):
            self.schema.labels(result).inc(0)
        self.risks = counter("risk_levels_total", "Resultados por nível de risco", ("level",))
        for level in ("BAIXO", "MEDIO", "ALTO", "INDETERMINADO"):
            self.risks.labels(level).inc(0)
        self.numeric = {
            "resumo_chars": histogram(
                "input_summary_chars", "Caracteres no resumo validado", SIZE_BUCKETS
            ),
            "detalhamento_chars": histogram(
                "input_detail_chars", "Caracteres no detalhamento validado", SIZE_BUCKETS
            ),
            "score_risco": histogram(
                "risk_score", "Score indicativo de risco", tuple(i / 10 for i in range(11))
            ),
            "fatores_count": histogram(
                "risk_factors", "Quantidade de fatores", (0, 1, 2, 3, 5, 10, 20)
            ),
            "prompt_tokens": histogram(
                "openrouter_prompt_tokens",
                "Tokens de entrada informados pelo provedor",
                TOKEN_BUCKETS,
            ),
            "completion_tokens": histogram(
                "openrouter_completion_tokens",
                "Tokens de geração, incluindo raciocínio",
                TOKEN_BUCKETS,
            ),
            "reasoning_tokens": histogram(
                "openrouter_reasoning_tokens",
                "Tokens de raciocínio informados pelo provedor",
                TOKEN_BUCKETS,
            ),
        }
        self.cost = counter("openrouter_cost_usd_total", "Custo em USD informado pelo provedor")

    def observe(self, record):
        endpoint = record["endpoint"]
        method = record["method"]
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            method = "OTHER"
        self.requests.labels(endpoint, method, str(record["status_code"])).inc()
        self.http_time.labels(endpoint, method).observe(record["http_latency_ms"] / 1000)
        self.request_size.labels(endpoint).observe(record["request_bytes"])
        source = record["result_source"]
        if source in SOURCES:
            self.sources.labels(source).inc()
            if record["analysis_ms"] is not None:
                self.analysis.labels(source).observe(record["analysis_ms"] / 1000)
        if source == "fallback":
            reason = record["remote_error"]
            self.fallback.labels(reason if reason in ERRORS else "unknown").inc()
        if record["remote_latency_ms"] is not None:
            self.remote_time.observe(record["remote_latency_ms"] / 1000)
        if record["schema_valid"] is not None:
            self.schema.labels("valid" if record["schema_valid"] else "invalid").inc()
        if record["nivel_risco"] in ("BAIXO", "MEDIO", "ALTO", "INDETERMINADO"):
            self.risks.labels(record["nivel_risco"]).inc()
        for name, metric in self.numeric.items():
            if record[name] is not None:
                metric.observe(record[name])
        if record["cost_usd"] is not None:
            self.cost.inc(record["cost_usd"])

    def render(self):
        return generate_latest(self.registry)
