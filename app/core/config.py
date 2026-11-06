from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRAVELTRACE_", env_file=".env", extra="ignore")

    database_url: SecretStr
    jwt_secret: SecretStr
    token_minutes: int = Field(default=120, ge=5, le=1440)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    db_pool_timeout_seconds: int = Field(default=5, ge=1, le=30)

    @field_validator("jwt_secret")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32 or value.get_secret_value().startswith("replace-with"):
            raise ValueError("Set a random JWT secret of at least 32 characters")
        return value
