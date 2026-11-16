"""Gera 30 atendimentos sequenciais por rodada, dos quais três tentam o OpenRouter."""

import argparse
import json
import time
from pathlib import Path

import httpx


def run(base_url, rounds, output, cases_path=None):
    cases_path = cases_path or Path(__file__).with_name("cases.json")
    cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))["cases"]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=180) as client:
        before = client.get("/metrics")
        before.raise_for_status()
        (output / "metrics_before.prom").write_text(before.text, encoding="utf-8")
        for round_number in range(rounds):
            for case in cases:
                started = time.perf_counter()
                row = {
                    "case": case["name"],
                    "expected_source": case["kind"],
                    "round": round_number + 1,
                    "expected_status": case["expected_status"],
                }
                try:
                    r = client.post("/predict", json=case["payload"])
                    row.update(
                        status_code=r.status_code,
                        request_id=r.headers.get("x-request-id"),
                        expected_status=case["expected_status"],
                    )
                except httpx.RequestError as exc:
                    row.update(status_code=None, request_id=None, error=type(exc).__name__)
                row["client_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
        after = client.get("/metrics")
        after.raise_for_status()
        (output / "metrics_after.prom").write_text(after.text, encoding="utf-8")
    (output / "load_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--output", default="monitoring/generated")
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds deve ser positivo")
    rows = run(args.base_url, args.rounds, args.output)
    mismatches = sum(r.get("status_code") != r.get("expected_status") for r in rows)
    print(
        f"Atendimentos: {len(rows)}; divergências HTTP: {mismatches}. Confira result_source no log para verificar os resultados remotos."
    )
    raise SystemExit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
