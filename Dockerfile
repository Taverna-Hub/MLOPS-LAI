# Dockerfile multi-stage otimizado para o Agente SIC-LAI com inferência em CPU
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    HF_HOME=/root/.cache/huggingface

WORKDIR /app

# Instala curl para healthchecks e uv
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

# Copia arquivos de definição e dependências
COPY pyproject.toml uv.lock ./

# Instala as dependências de produção com uv
RUN uv sync --frozen --no-dev

# Pré-download do modelo Qwen2.5-0.5B-Instruct durante o build (garante execução 100% offline)
RUN uv run python -c "from transformers import AutoTokenizer, AutoModelForCausalLM; \
    model_id = 'Qwen/Qwen2.5-0.5B-Instruct'; \
    print(f'Baixando {model_id} durante o build...'); \
    AutoTokenizer.from_pretrained(model_id); \
    AutoModelForCausalLM.from_pretrained(model_id); \
    print('Modelo baixado com sucesso!')"

# Copia código fonte da aplicação
COPY src/ ./src/
COPY README.md LICENSE ./

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["uv", "run", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
