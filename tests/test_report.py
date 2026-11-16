import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from monitoring.report import describe, percentile, read_records, summarize
from src.agent.analyzer import _classificar_heuristicamente
from src.monitoring import new_record
from src.schemas import PedidoLAIRequest


class ReportTests(unittest.TestCase):
    def test_load_has_exactly_three_open_requests(self):
        cases = json.loads(Path("monitoring/cases.json").read_text(encoding="utf-8"))["cases"]
        self.assertEqual(
            Counter(c["kind"] for c in cases),
            {"heuristica": 19, "abstencao": 4, "validacao": 4, "modelo_remoto": 3},
        )
        for case in cases:
            if case["kind"] == "validacao":
                with self.assertRaises(ValidationError):
                    PedidoLAIRequest(**case["payload"])
            elif case["kind"] == "modelo_remoto":
                self.assertEqual(
                    _classificar_heuristicamente(PedidoLAIRequest(**case["payload"]))[
                        "score_risco"
                    ],
                    0.5,
                )

    def test_statistics_match_inclusive_quartiles_and_outliers(self):
        result = describe([1, 2, 3, 4, 100])
        self.assertEqual(result["q1"], 2)
        self.assertEqual(result["median"], 3)
        self.assertEqual(result["upper_whisker"], 4)
        self.assertEqual(result["outliers"], [100])
        self.assertAlmostEqual(percentile([0, 10], 0.25), 2.5)
        self.assertEqual(describe([]), {"count": 0})
        self.assertEqual(describe([0])["mean"], 0)

    def test_missing_usage_is_not_zero_or_schema_failure(self):
        base = new_record("POST") | {
            "endpoint": "/predict",
            "status_code": 200,
            "http_latency_ms": 1,
        }
        report = summarize(
            [
                base,
                base | {"cost_usd": 0, "schema_valid": False},
                base | {"schema_valid": True, "prompt_tokens": 0},
            ]
        )
        self.assertEqual(report["statistics"]["cost_usd"]["count"], 1)
        self.assertEqual(report["statistics"]["cost_usd"]["mean"], 0)
        self.assertEqual(report["schema_valid_rate"], 0.5)
        self.assertIsNone(summarize([])["error_rate_4xx"])

    def test_filter_deduplication_and_invalid_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            row = new_record("POST") | {"timestamp": "2026-11-16T10:00:00+00:00"}
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertEqual(len(read_records([path, path], {row["request_id"]})), 1)
            self.assertEqual(read_records([path], {"other"}), [])
            path.write_text("broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "linha 1"):
                read_records([path])
