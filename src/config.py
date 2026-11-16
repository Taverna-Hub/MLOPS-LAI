"""Configurações da aplicação utilizando Pydantic Settings."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações de runtime do serviço de inferência SIC-LAI."""

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    MODEL_NAME: str = "nvidia/nemotron-3.5-super-vl:free"
    LOG_LEVEL: str = "info"
    VERSION: str = "1.0.0"
    OPENROUTER_API_KEY: SecretStr = SecretStr("")
    OPENROUTER_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)
    OPENROUTER_MAX_TOKENS: int = Field(default=4096, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.OPENROUTER_API_KEY.get_secret_value().strip())


settings = Settings()
