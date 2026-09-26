from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    world_id_rp_id: str
    world_id_environment: Literal[
        "production",
        "staging",
        "sandbox",
    ] = "production"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
