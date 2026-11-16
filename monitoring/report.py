"""Analisa JSONL e prepara dados de planilha sem alterar os arquivos originais."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

NUMERIC = (
    "http_latency_ms",
    "analysis_ms",
    "remote_latency_ms",
    "request_bytes",
    "resumo_chars",
    "detalhamento_chars",
    "score_risco",
    "fatores_count",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "cost_usd",
)
CATEGORIES = (
    "orgao_destinatario",
    "origem_solicitacao",
    "forma_resposta",
    "result_source",
    "nivel_risco",
    "remote_error",
)


def percentile(values, p):
    """Interpolação linear inclusiva, equivalente a PERCENTILE.INC do Excel."""
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * p
    lo = int(index)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def describe(values):
    if not values:
        return {"count": 0}
    q1, median, q3 = (percentile(values, p) for p in (0.25, 0.5, 0.75))
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = [v for v in values if lower <= v <= upper]
    return dict(
        count=len(values),
        mean=sum(values) / len(values),
        min=min(values),
        q1=q1,
        median=median,
        q3=q3,
        max=max(values),
        p95=percentile(values, 0.95),
        iqr=iqr,
        lower_fence=lower,
        upper_fence=upper,
        lower_whisker=min(inside),
        upper_whisker=max(inside),
        outliers=[v for v in values if v < lower or v > upper],
    )


def read_records(paths, ids=None):
    records = []
    seen = set()
    for path in paths:
        for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"JSONL inválido: {path}, linha {number}") from exc
            if row.get("schema_version") != 1:
                raise ValueError(f"Versão de registro não suportada: {path}, linha {number}")
            request_id = row["request_id"]
            if (ids is not None and request_id not in ids) or request_id in seen:
                continue
            seen.add(request_id)
            records.append(row)
    return sorted(records, key=lambda row: row["timestamp"])


def summarize(records):
    total = len(records)
    errors4 = sum(400 <= r["status_code"] < 500 for r in records)
    errors5 = sum(r["status_code"] >= 500 for r in records)
    valid = sum(r["schema_valid"] is True for r in records)
    invalid = sum(r["schema_valid"] is False for r in records)
    sources = dict(Counter(r["result_source"] for r in records if r["result_source"] is not None))
    return {
        "requests": total,
        "errors_4xx": errors4,
        "errors_5xx": errors5,
        "error_rate_4xx": errors4 / total if total else None,
        "error_rate_5xx": errors5 / total if total else None,
        "schema_valid": valid,
        "schema_invalid": invalid,
        "schema_valid_rate": valid / (valid + invalid) if valid + invalid else None,
        "sources": sources,
        "statistics": {
            key: describe(
                [
                    r[key]
                    for r in records
                    if type(r.get(key)) in (int, float) and math.isfinite(r[key])
                ]
            )
            for key in NUMERIC
        },
        "categories": {
            key: dict(Counter(r[key] for r in records if r.get(key) is not None))
            for key in CATEGORIES
        },
        "endpoints": {
            endpoint: describe([r["http_latency_ms"] for r in records if r["endpoint"] == endpoint])
            for endpoint in sorted({r["endpoint"] for r in records})
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", nargs="+", default=["logs/requests.jsonl"])
    parser.add_argument("--load-results", help="Limita aos request_id da rodada de carga")
    parser.add_argument("--output", default="monitoring/generated/report.json")
    args = parser.parse_args()
    ids = None
    if args.load_results:
        rows = json.loads(Path(args.load_results).read_text(encoding="utf-8"))
        ids = {r["request_id"] for r in rows if r.get("request_id")}
    records = read_records(args.log, ids)
    if not records:
        parser.error("Nenhum registro encontrado para os filtros fornecidos")
    if ids is not None and len(records) != len(ids):
        parser.error("Faltam registros da carga; inclua também os arquivos rotacionados em --log")
    report = {"data_source": "observed", "records": records, "summary": summarize(records)}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
