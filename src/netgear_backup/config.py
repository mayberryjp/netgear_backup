from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NETGEAR_", extra="ignore")

    base_url: str = "http://netgearswitch.office.mayberry.farm"
    username: str = "admin"
    password: str = Field(...)
    verify_tls: bool = False
    request_timeout_seconds: int = 30

    # Path and form fields of the switch login form; adjust per firmware.
    login_path: str = "/iss/specific/login.html"
    login_username_field: str = "username"
    login_password_field: str = "password"

    # Optional pre-issued session token; skips login when set (it expires with the web session).
    gambit: str = ""

    backup_dir: str = "/backups"
    interval_seconds: int = 86400
    retention_count: int = 30
    max_attempts: int = 3
    retry_delay_seconds: int = 30

    log_level: str = "INFO"


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
