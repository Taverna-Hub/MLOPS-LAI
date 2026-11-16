"""Valida os artefatos demonstrativos contra os registros de origem."""

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from prometheus_client.parser import text_string_to_metric_families

from monitoring.report import read_records, summarize

EXAMPLES = Path("monitoring/examples")


class ExampleTests(unittest.TestCase):
    def test_real_measurements_of_fictional_requests_reconcile(self):
        rows = read_records([EXAMPLES / "requests.jsonl"])
        summary = summarize(rows)
        expected = json.loads((EXAMPLES / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(summary, expected["summary"])
        self.assertEqual(summary["requests"], 30)
        self.assertEqual(summary["errors_4xx"], 4)
        self.assertEqual(summary["schema_valid"], 3)
        self.assertEqual(summary["sources"], {"heuristica": 19, "abstencao": 4, "modelo_remoto": 3})
        for row in rows:
            for forbidden in (
                "protocolo",
                "resumo_solicitacao",
                "detalhamento_solicitacao",
                "fatores_risco",
                "recomendacao_sic",
            ):
                self.assertNotIn(forbidden, row)
        text = (EXAMPLES / "metrics_after.prom").read_text()
        samples = [
            sample for family in text_string_to_metric_families(text) for sample in family.samples
        ]
        count = sum(
            s.value
            for s in samples
            if s.name == "sic_lai_http_requests_total" and s.labels["endpoint"] == "/predict"
        )
        self.assertEqual(count, len(rows))

    def test_workbook_preserves_formulas_charts_and_cached_results(self):
        ns = {
            "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
        }
        with ZipFile(EXAMPLES / "monitoramento.xlsx") as archive:
            self.assertIsNone(archive.testzip())
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))

            def value(address):
                return float(sheet.find(f'.//s:c[@r="{address}"]/s:v', ns).text)

            self.assertEqual(value("B6"), 30)
            self.assertEqual(value("B11"), 3)
            self.assertEqual(value("B12"), 0)
            self.assertAlmostEqual(value("B9"), 4 / 30)
            self.assertEqual(value("B21"), 0)
            self.assertEqual(value("B22"), 3)
            self.assertIsNotNone(sheet.find('.//s:c[@r="B9"]/s:f', ns))
            charts = [p for p in archive.namelist() if "/charts/chart" in p and p.endswith(".xml")]
            self.assertEqual(len(charts), 4)
            scatter = ET.fromstring(archive.read(charts[-1]))
            self.assertEqual(scatter.find(".//c:scatterStyle", ns).get("val"), "line")
            self.assertIsNotNone(scatter.find(".//c:yVal/c:numRef/c:f", ns))
