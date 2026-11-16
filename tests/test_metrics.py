"""Reconciliação de métricas e eventos, sem registro global compartilhado."""

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.responses import Response
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
from test_monitoring import make_app
from test_openrouter import PEDIDO

from src.metrics import Metrics
from src.monitoring import new_record


def samples(metrics):
    return {
        (s.name, tuple(sorted(s.labels.items()))): s.value
        for family in text_string_to_metric_families(metrics.render().decode())
        for s in family.samples
    }


class MetricsTests(unittest.TestCase):
    def test_http_counts_latency_size_and_scrape_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requests.jsonl"
            metrics = Metrics()
            api, sink = make_app(path, metrics.observe)
            api.get("/metrics")(lambda: Response(metrics.render(), media_type="text/plain"))
            try:
                with TestClient(api) as client:
                    client.post("/predict", json=PEDIDO | {"resumo_solicitacao": "edital"})
                    client.post("/predict", json={})
                    client.get("/health")
                    before = samples(metrics)
                    for _ in range(3):
                        self.assertEqual(client.get("/metrics").status_code, 200)
                    self.assertEqual(samples(metrics), before)
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(rows), 3)
                registry = metrics.registry
                self.assertEqual(
                    registry.get_sample_value(
                        "sic_lai_http_requests_total",
                        {"endpoint": "/predict", "method": "POST", "status": "422"},
                    ),
                    1,
                )
                self.assertEqual(
                    registry.get_sample_value(
                        "sic_lai_http_duration_seconds_count",
                        {"endpoint": "/predict", "method": "POST"},
                    ),
                    2,
                )
                self.assertAlmostEqual(
                    registry.get_sample_value(
                        "sic_lai_http_duration_seconds_sum",
                        {"endpoint": "/predict", "method": "POST"},
                    ),
                    sum(r["http_latency_ms"] for r in rows if r["endpoint"] == "/predict") / 1000,
                )
                self.assertEqual(
                    registry.get_sample_value(
                        "sic_lai_http_request_bytes_sum", {"endpoint": "/predict"}
                    ),
                    sum(r["request_bytes"] for r in rows if r["endpoint"] == "/predict"),
                )
                output = metrics.render().decode()
                self.assertIn("# HELP", output)
                self.assertIn("# TYPE", output)
                self.assertNotIn("IBAMA", output)
                self.assertNotIn("python_gc", output)
            finally:
                sink.close()

    def test_sources_schema_denominator_tokens_and_zero_vs_absent(self):
        metrics = Metrics()
        base = new_record("POST") | {
            "endpoint": "/predict",
            "status_code": 200,
            "http_latency_ms": 10,
            "result_source": "fallback",
            "remote_error": "http_error",
        }
        metrics.observe(base)
        registry = metrics.registry
        self.assertEqual(
            registry.get_sample_value("sic_lai_remote_schema_total", {"result": "invalid"}), 0
        )
        self.assertEqual(registry.get_sample_value("sic_lai_openrouter_prompt_tokens_count"), 0)
        metrics.observe(
            base
            | {
                "schema_valid": False,
                "remote_error": "invalid_output",
                "prompt_tokens": 10,
                "completion_tokens": 30,
                "reasoning_tokens": 20,
                "cost_usd": 0,
            }
        )
        metrics.observe(
            base
            | {
                "schema_valid": True,
                "result_source": "modelo_remoto",
                "remote_error": None,
                "prompt_tokens": 0,
                "cost_usd": 0.125,
            }
        )
        self.assertEqual(
            registry.get_sample_value("sic_lai_remote_schema_total", {"result": "invalid"}), 1
        )
        self.assertEqual(
            registry.get_sample_value("sic_lai_remote_schema_total", {"result": "valid"}), 1
        )
        self.assertEqual(registry.get_sample_value("sic_lai_openrouter_prompt_tokens_count"), 2)
        self.assertEqual(registry.get_sample_value("sic_lai_openrouter_prompt_tokens_sum"), 10)
        self.assertEqual(registry.get_sample_value("sic_lai_openrouter_completion_tokens_sum"), 30)
        self.assertEqual(registry.get_sample_value("sic_lai_openrouter_reasoning_tokens_sum"), 20)
        self.assertEqual(registry.get_sample_value("sic_lai_openrouter_cost_usd_total"), 0.125)

    def test_new_instance_starts_with_empty_history(self):
        metrics = Metrics()
        metrics.observe(
            new_record("GET") | {"endpoint": "/health", "status_code": 200, "http_latency_ms": 1}
        )
        other = Metrics()
        self.assertIsNone(
            other.registry.get_sample_value(
                "sic_lai_http_requests_total",
                {"endpoint": "/health", "method": "GET", "status": "200"},
            )
        )
