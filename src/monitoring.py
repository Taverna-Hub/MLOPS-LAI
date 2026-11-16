"""Rastro por requisição: somente medidas e categorias, nunca corpos HTTP."""

import json
import logging
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from src.config import settings

trace: ContextVar[dict | None] = ContextVar("request_trace", default=None)


def update_trace(**fields):
    """Atualiza somente o contexto da requisição corrente."""
    record = trace.get()
    if record is not None:
        record.update(fields)


class ByteRotatingHandler(RotatingFileHandler):
    """Conta bytes UTF-8, em vez de caracteres, para o limite de rotação."""

    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        size = len((self.format(record) + self.terminator).encode("utf-8"))
        return self.stream.tell() > 0 and self.stream.tell() + size >= self.maxBytes


class JsonlSink:
    def __init__(self, path, max_bytes=10_000_000, backups=5):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.handler = ByteRotatingHandler(
            path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        self.handler.setFormatter(logging.Formatter("%(message)s"))

    def write(self, record):
        message = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        # Handler.handle serializa threads; emit faz flush e reporta falhas no stderr.
        self.handler.handle(logging.makeLogRecord({"msg": message, "levelno": logging.INFO}))

    def close(self):
        self.handler.close()


def new_record(method):
    return {
        "schema_version": 1,
        "service_version": settings.VERSION,
        "timestamp": None,
        "request_id": str(uuid4()),
        "method": method,
        "endpoint": None,
        "status_code": None,
        "outcome": None,
        "http_latency_ms": None,
        "request_bytes": 0,
        "analysis_ms": None,
        "orgao_destinatario": None,
        "origem_solicitacao": None,
        "forma_resposta": None,
        "resumo_chars": None,
        "detalhamento_chars": None,
        "result_source": None,
        "nivel_risco": None,
        "score_risco": None,
        "fatores_count": None,
        "remote_attempted": False,
        "remote_latency_ms": None,
        "remote_status_code": None,
        "remote_error": None,
        "schema_valid": None,
        "requested_model": None,
        "served_model": None,
        "provider": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": None,
    }


class MonitoringMiddleware:
    def __init__(self, app, sink=None, observer=None):
        self.app = app
        self.sink = sink or JsonlSink(
            settings.MONITORING_LOG_PATH,
            settings.MONITORING_MAX_BYTES,
            settings.MONITORING_BACKUPS,
        )
        self.observer = observer

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/metrics":
            return await self.app(scope, receive, send)
        record = new_record(scope["method"])
        token = trace.set(record)
        start = time.perf_counter()

        async def observed_receive():
            message = await receive()
            if message["type"] == "http.request":
                record["request_bytes"] += len(message.get("body", b""))
            return message

        async def observed_send(message):
            if message["type"] == "http.response.start":
                record["status_code"] = message["status"]
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", record["request_id"].encode("ascii"))
                ]
            await send(message)

        try:
            await self.app(scope, observed_receive, observed_send)
        except BaseException:
            record["status_code"] = record["status_code"] or 500
            record["outcome"] = "internal_error"
            raise
        finally:
            record["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            record["http_latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
            route = scope.get("route")
            record["endpoint"] = getattr(route, "path", "__unmatched__")
            status = record["status_code"] or 500
            record["status_code"] = status
            if record["outcome"] is None:
                record["outcome"] = (
                    "server_error"
                    if status >= 500
                    else (
                        "validation_error"
                        if status == 422
                        else ("client_error" if status >= 400 else "success")
                    )
                )
            try:
                self.sink.write(record)
                if self.observer:
                    self.observer(record)
            finally:
                trace.reset(token)
