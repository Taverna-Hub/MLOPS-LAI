"""Persistência e isolamento do rastro, usando somente dados fictícios."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_openrouter import ANALISE, PEDIDO, completion, provider_mock

from src.app import predict, validation_exception_handler
from src.config import settings
from src.monitoring import JsonlSink, MonitoringMiddleware, trace


def make_app(path, observer=None):
    api = FastAPI()
    sink = JsonlSink(path)
    api.add_middleware(MonitoringMiddleware, sink=sink, observer=observer)
    api.post("/predict")(predict)
    api.get("/health")(lambda: {"status": "healthy"})
    api.add_exception_handler(RequestValidationError, validation_exception_handler)
    return api, sink


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "requests.jsonl"
        self.api, self.sink = make_app(self.path)
        self.addCleanup(self.sink.close)

    def records(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def test_append_sizes_categories_and_privacy(self):
        pedido = PEDIDO | {"resumo_solicitacao": "edital", "protocolo": "SECRET-PROTOCOL"}
        with TestClient(self.api) as client:
            r = client.post("/predict", json=pedido)
            first = self.path.read_bytes()
            client.post("/predict", json=pedido | {"orgao_destinatario": 'Órgão "A"\nB'})
        self.assertTrue(self.path.read_bytes().startswith(first))
        records = self.records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["request_id"], r.headers["x-request-id"])
        self.assertEqual(records[0]["request_bytes"], len(r.request.content))
        self.assertEqual(records[0]["resumo_chars"], len("edital"))
        self.assertEqual(records[0]["result_source"], "heuristica")
        self.assertEqual(records[0]["fatores_count"], 2)
        self.assertIsNone(records[0]["cost_usd"])
        self.assertIsNone(records[0]["schema_valid"])
        self.assertIn("+00:00", records[0]["timestamp"])
        raw = self.path.read_text(encoding="utf-8")
        for forbidden in [
            "SECRET-PROTOCOL",
            PEDIDO["detalhamento_solicitacao"],
            "recomendacao_sic",
        ]:
            self.assertNotIn(forbidden, raw)

    def test_validation_abstention_unknown_route_and_internal_error(self):
        @self.api.get("/fail")
        def fail():
            raise RuntimeError("secret-exception-body")

        with TestClient(self.api, raise_server_exceptions=False) as client:
            self.assertEqual(
                client.post("/predict", json={"secret": "payload-secret"}).status_code, 422
            )
            client.post("/predict", json=PEDIDO | {"orgao_destinatario": " "})
            client.get("/arbitrary-secret-path")
            self.assertEqual(client.get("/fail").status_code, 500)
            client.get("/metrics")
        rows = self.records()
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["outcome"], "validation_error")
        self.assertIsNone(rows[0]["resumo_chars"])
        self.assertEqual(rows[1]["result_source"], "abstencao")
        self.assertEqual(rows[2]["endpoint"], "__unmatched__")
        self.assertEqual(rows[3]["outcome"], "internal_error")
        raw = self.path.read_text(encoding="utf-8")
        for secret in ["payload-secret", "secret-exception-body", "arbitrary-secret-path"]:
            self.assertNotIn(secret, raw)
        self.assertIsNone(trace.get())

    def test_remote_usage_zero_cost_and_invalid_output_preserve_usage(self):
        response = completion()
        response.update(
            model=settings.MODEL_NAME,
            provider="Nvidia",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "cost": 0,
                "completion_tokens_details": {"reasoning_tokens": 150},
            },
        )
        with patch.object(settings, "OPENROUTER_API_KEY", SecretStr("test-key")):
            with TestClient(self.api) as client:
                with provider_mock(lambda request: httpx.Response(200, json=response)):
                    client.post("/predict", json=PEDIDO)
                response["choices"][0]["message"]["content"] = "invalid-sensitive-output"
                with provider_mock(lambda request: httpx.Response(200, json=response)):
                    client.post("/predict", json=PEDIDO)
        a, b = self.records()
        self.assertEqual(a["result_source"], "modelo_remoto")
        self.assertTrue(a["schema_valid"])
        self.assertEqual(a["completion_tokens"], 200)
        self.assertEqual(a["reasoning_tokens"], 150)
        self.assertEqual(a["cost_usd"], 0)
        self.assertEqual(b["result_source"], "fallback")
        self.assertFalse(b["schema_valid"])
        self.assertEqual(b["remote_error"], "invalid_output")
        self.assertEqual(b["prompt_tokens"], 100)
        self.assertNotIn("invalid-sensitive-output", self.path.read_text())

    def test_missing_key_and_http_error_are_not_schema_failures(self):
        with TestClient(self.api) as client:
            with patch.object(settings, "OPENROUTER_API_KEY", SecretStr("")):
                client.post("/predict", json=PEDIDO)
            with patch.object(settings, "OPENROUTER_API_KEY", SecretStr("test-key")):
                with provider_mock(lambda request: httpx.Response(429, text="secret-body")):
                    client.post("/predict", json=PEDIDO)
        missing, failed = self.records()
        self.assertFalse(missing["remote_attempted"])
        self.assertEqual(missing["remote_error"], "not_configured")
        self.assertTrue(failed["remote_attempted"])
        self.assertEqual(failed["remote_status_code"], 429)
        self.assertIsNone(failed["schema_valid"])
        self.assertIsNone(failed["prompt_tokens"])
        self.assertNotIn("secret-body", self.path.read_text())

    def test_rotation_counts_utf8_bytes_and_keeps_five_backups(self):
        path = Path(self.tmp.name) / "rotation.jsonl"
        sink = JsonlSink(path, max_bytes=230, backups=5)
        try:
            for n in range(20):
                sink.write({"n": n, "category": "Órgão" * 12})
        finally:
            sink.close()
        files = list(Path(self.tmp.name).glob("rotation.jsonl*"))
        self.assertEqual(len(files), 6)
        numbers = []
        for p in files:
            self.assertLess(p.stat().st_size, 230)
            numbers.extend(
                json.loads(line)["n"] for line in p.read_text(encoding="utf-8").splitlines()
            )
        self.assertIn(19, numbers)
        self.assertNotIn(0, numbers)

    def test_restart_appends_to_existing_file(self):
        self.sink.write({"n": 1})
        self.sink.close()
        other = JsonlSink(self.path)
        try:
            other.write({"n": 2})
        finally:
            other.close()
        self.assertEqual(self.records(), [{"n": 1}, {"n": 2}])

    def test_rotation_accounts_for_platform_line_endings(self):
        path = Path(self.tmp.name) / "boundary.jsonl"
        event = {"category": "Órgão"}
        size = len(
            (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + os.linesep).encode(
                "utf-8"
            )
        )
        sink = JsonlSink(path, max_bytes=2 * size, backups=5)
        try:
            sink.write(event)
            sink.write(event)
        finally:
            sink.close()
        self.assertEqual(path.stat().st_size, size)
        self.assertEqual(Path(str(path) + ".1").stat().st_size, size)


class ConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_requests_do_not_mix_contexts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parallel.jsonl"
            api, sink = make_app(path)

            async def fake(messages):
                from src.monitoring import update_trace
                from src.schemas import AnaliseRisco

                update_trace(provider="Nvidia")
                await asyncio.sleep(0.001)
                return AnaliseRisco(**ANALISE)

            try:
                with patch("src.agent.analyzer.generate_analysis", side_effect=fake):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=api), base_url="http://test"
                    ) as client:
                        await asyncio.gather(
                            *[
                                client.post(
                                    "/predict",
                                    json=PEDIDO
                                    | {
                                        "orgao_destinatario": f"Órgão {i}",
                                        "resumo_solicitacao": "X" * (i + 1),
                                    },
                                )
                                for i in range(20)
                            ]
                        )
            finally:
                sink.close()
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len({r["request_id"] for r in rows}), 20)
            for r in rows:
                i = int(r["orgao_destinatario"].split()[-1])
                self.assertEqual(r["resumo_chars"], i + 1)
                self.assertEqual(r["provider"], "Nvidia")
            self.assertIsNone(trace.get())
