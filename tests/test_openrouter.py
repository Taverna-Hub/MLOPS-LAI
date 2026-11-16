"""Regressões da migração para inferência remota, sem chamadas externas."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.app import app
from src.config import settings
from src.models.openrouter import OPENROUTER_URL, OpenRouterError, generate_analysis
from src.schemas import FORBIDDEN_T0_FIELDS, AnaliseRisco

ANALISE = {
    "nivel_risco": "ALTO",
    "score_risco": 0.83,
    "fatores_risco": ["Necessidade de análise pela unidade responsável"],
    "recomendacao_sic": "Confirmar o aceite e acompanhar a análise.",
}
PEDIDO = {
    "protocolo": "TESTE-001",
    "data_registro": "2026-11-16T10:00:00Z",
    "orgao_destinatario": "IBAMA",
    "origem_solicitacao": "Internet",
    "forma_resposta": "E-mail",
    "resumo_solicitacao": "Visita técnica",
    "detalhamento_solicitacao": "Solicito informar documentos e etapas para uma visita técnica.",
}
MESSAGES = [{"role": "user", "content": "Pedido fictício"}]


def completion(content=None, finish_reason="stop"):
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": json.dumps(ANALISE) if content is None else content},
            }
        ],
    }


def provider_mock(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return patch("src.models.openrouter.httpx.AsyncClient", return_value=client)


class RemoteClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        key_patch = patch.object(settings, "OPENROUTER_API_KEY", SecretStr("test-key"))
        key_patch.start()
        self.addCleanup(key_patch.stop)

    async def test_request_sends_schema_and_requires_compatible_provider(self):
        def handler(request):
            self.assertEqual(str(request.url), OPENROUTER_URL)
            self.assertEqual(request.headers["Authorization"], "Bearer test-key")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "nvidia/nemotron-3.5-super-vl:free")
            self.assertEqual(body["messages"], MESSAGES)
            self.assertEqual(body["provider"], {"require_parameters": True})
            self.assertNotIn("models", body)
            fmt = body["response_format"]
            self.assertEqual(fmt["type"], "json_schema")
            self.assertTrue(fmt["json_schema"]["strict"])
            schema = fmt["json_schema"]["schema"]
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(ANALISE))
            self.assertEqual(schema["properties"]["score_risco"]["maximum"], 1.0)
            return httpx.Response(200, json=completion())

        with provider_mock(handler):
            result = await generate_analysis(MESSAGES)
        self.assertEqual(result.model_dump(mode="json"), ANALISE)

    async def test_missing_key_does_not_send_request(self):
        with patch.object(settings, "OPENROUTER_API_KEY", SecretStr(" ")):
            with patch("src.models.openrouter.httpx.AsyncClient") as client:
                with self.assertRaisesRegex(OpenRouterError, "não configurada"):
                    await generate_analysis(MESSAGES)
                client.assert_not_called()

    async def test_http_errors_do_not_expose_provider_body_or_key(self):
        for status in [401, 402, 404, 429, 500, 503]:
            with self.subTest(status=status):

                def handler(request):
                    return httpx.Response(status, json={"error": "sensitive-provider-body"})

                with provider_mock(handler):
                    with self.assertRaises(OpenRouterError) as result:
                        await generate_analysis(MESSAGES)
                self.assertIn(str(status), str(result.exception))
                self.assertNotIn("sensitive-provider-body", str(result.exception))
                self.assertNotIn("test-key", str(result.exception))

    async def test_timeout_is_a_recoverable_error(self):
        def handler(request):
            raise httpx.ReadTimeout("sensitive-provider-body", request=request)

        with provider_mock(handler):
            with self.assertRaisesRegex(OpenRouterError, "ReadTimeout") as result:
                await generate_analysis(MESSAGES)
        self.assertNotIn("sensitive-provider-body", str(result.exception))

    async def test_invalid_envelopes_or_model_outputs_are_rejected(self):
        bad_results = [
            {},
            [],
            {"error": {"message": "sensitive-provider-body"}},
            {"choices": []},
            {"choices": [None]},
            completion(content="not JSON"),
            completion(content="[]"),
            completion(content="{}"),
            completion(content=json.dumps(ANALISE | {"score_risco": 1.1})),
            completion(content=json.dumps(ANALISE | {"score_risco": float("nan")})),
            completion(content=json.dumps(ANALISE | {"fatores_risco": "invalid"})),
            completion(content=json.dumps(ANALISE | {"fatores_risco": []})),
            completion(content=json.dumps(ANALISE | {"nivel_risco": "OTHER"})),
            completion(content=json.dumps(ANALISE | {"extra": "invalid"})),
            completion(content=json.dumps(ANALISE | {"recomendacao_sic": ""})),
            completion(finish_reason="length"),
            completion(finish_reason="content_filter"),
        ]
        for payload in bad_results:
            with self.subTest(payload=payload):
                with provider_mock(lambda request: httpx.Response(200, json=payload)):
                    with self.assertRaises(OpenRouterError):
                        await generate_analysis(MESSAGES)

    async def test_non_json_provider_response_is_rejected(self):
        with provider_mock(lambda request: httpx.Response(200, text="upstream unavailable")):
            with self.assertRaises(OpenRouterError):
                await generate_analysis(MESSAGES)

    async def test_markdown_json_is_validated(self):
        content = "```json\n" + json.dumps(ANALISE) + "\n```"
        with provider_mock(lambda request: httpx.Response(200, json=completion(content))):
            result = await generate_analysis(MESSAGES)
        self.assertEqual(result.score_risco, 0.83)

    async def test_health_is_responsive_while_waiting_for_provider(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(request):
            entered.set()
            await release.wait()
            return httpx.Response(200, json=completion())

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as api:
            with provider_mock(handler):
                prediction = asyncio.create_task(api.post("/predict", json=PEDIDO))
                try:
                    await asyncio.wait_for(entered.wait(), timeout=1)
                    health = await asyncio.wait_for(api.get("/health"), timeout=1)
                    self.assertEqual(health.status_code, 200)
                    self.assertFalse(prediction.done())
                finally:
                    release.set()
                    result = await prediction
                self.assertEqual(result.status_code, 200)


class ApiTests(unittest.TestCase):
    def test_remote_result_preserves_response_contract(self):
        remote = AsyncMock(return_value=AnaliseRisco(**ANALISE))
        with patch("src.agent.analyzer.generate_analysis", remote), TestClient(app) as client:
            r = client.post("/predict", json=PEDIDO)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["nivel_risco"], "ALTO")
        self.assertEqual(r.json()["protocolo"], PEDIDO["protocolo"])
        self.assertEqual(set(r.json()), set(ANALISE) | {"protocolo", "tempo_processamento_ms"})
        messages = remote.call_args.args[0]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn(PEDIDO["detalhamento_solicitacao"], messages[1]["content"])
        self.assertNotIn("<|im_start|>", messages[1]["content"])

    def test_provider_failure_uses_existing_fallback(self):
        with patch("src.agent.analyzer.generate_analysis", side_effect=OpenRouterError("HTTP 429")):
            with TestClient(app) as client:
                r = client.post("/predict", json=PEDIDO)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["nivel_risco"], "MEDIO")
        self.assertEqual(r.json()["score_risco"], 0.50)

    def test_known_rules_and_abstention_skip_remote_inference(self):
        cases = [
            ({"resumo_solicitacao": "Solicito microdados"}, "ALTO", 0.88),
            ({"orgao_destinatario": "Universidade Federal"}, "BAIXO", 0.12),
            ({"orgao_destinatario": "INSS"}, "MEDIO", 0.58),
            ({"orgao_destinatario": " "}, "INDETERMINADO", 0.0),
            ({"detalhamento_solicitacao": "abc"}, "INDETERMINADO", 0.0),
        ]
        with patch("src.agent.analyzer.generate_analysis") as remote, TestClient(app) as client:
            for fields, risk, score in cases:
                with self.subTest(fields=fields):
                    r = client.post("/predict", json=PEDIDO | fields)
                    self.assertEqual(r.status_code, 200)
                    self.assertEqual(r.json()["nivel_risco"], risk)
                    self.assertEqual(r.json()["score_risco"], score)
            remote.assert_not_called()

    def test_temporal_leakage_is_rejected_before_remote_call(self):
        with patch("src.agent.analyzer.generate_analysis") as remote, TestClient(app) as client:
            for field in FORBIDDEN_T0_FIELDS:
                with self.subTest(field=field):
                    r = client.post("/predict", json=PEDIDO | {field: None})
                    self.assertEqual(r.status_code, 422)
                    self.assertEqual(r.json()["detail"][0]["loc"], ["body", field])
            remote.assert_not_called()

    def test_health_describes_configuration_without_contacting_provider(self):
        with patch("src.agent.analyzer.generate_analysis") as remote, TestClient(app) as client:
            for key, status in [("", "degraded"), ("test-key", "healthy")]:
                with patch.object(settings, "OPENROUTER_API_KEY", SecretStr(key)):
                    r = client.get("/health")
                    self.assertEqual(r.status_code, 200)
                    self.assertEqual(r.json()["status"], status)
                    self.assertEqual(r.json()["device"], "remote")
            remote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
