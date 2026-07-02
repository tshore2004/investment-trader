from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = Field(..., description="asyncpg DSN for TimescaleDB")

    # Interactive Brokers
    ib_host: str = "127.0.0.1"
    ib_port: int = 7497
    ib_client_id: int = 1
    ib_account: str = ""

    # Risk limits
    max_position_usd: float = 50_000.0
    max_portfolio_drawdown_pct: float = 0.05
    max_order_size: int = 100

    # Trading / strategy
    trading_enabled: bool = False
    max_trades_per_day: int = 5
    watchlist_symbols: str = "AAPL"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    def watchlist(self) -> list[str]:
        """Parse WATCHLIST_SYMBOLS (comma-separated) into a clean symbol list."""
        return [s.strip().upper() for s in self.watchlist_symbols.split(",") if s.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]