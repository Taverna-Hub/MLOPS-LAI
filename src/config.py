"""Configurações da aplicação utilizando Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações de runtime do serviço de inferência SIC-LAI."""

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    MODEL_NAME: str = "Qwen/Qwen2.5-0.5B-Instruct"
    DEVICE: str = "cpu"
    LOG_LEVEL: str = "info"
    VERSION: str = "1.0.0"
    USE_SLM: bool = True
    LOCAL_FILES_ONLY: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
