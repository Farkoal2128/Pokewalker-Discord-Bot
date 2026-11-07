"""Protected credentials and explicit runtime configuration (C5)."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path


LOG = logging.getLogger(__name__)


@dataclass(frozen=True, repr=False)
class Secret:
    value: str

    def __repr__(self):
        return "***"

    __str__ = __repr__


def snowflake(value):
    if not value.isascii() or not value.isdecimal() or not 0 < int(value) < 2**64:
        raise ValueError("Discord IDs must be positive 64-bit integers")
    return int(value)


@dataclass(frozen=True)
class Settings:
    token: Secret
    db_path: Path = Path("pokewalker.sqlite3")
    content_path: Path = Path("content/artifact/content.json")
    owner_ids: frozenset[int] = frozenset()
    allow_unpatched_sqlite: bool = False
    dev_guild_id: int | None = None
    marker_log_path: Path | None = None
    privacy_path: Path | None = None
    admin_guild_id: int | None = None
    release: str = "dev"
    heartbeat_url: Secret | None = None

    def __post_init__(self):
        if not self.token.value:
            raise ValueError("Discord token is required")
        if not self.owner_ids and self.dev_guild_id is None:
            raise ValueError("Production requires a nonempty owner ID allowlist")
        marker = self.marker_log_path or self.db_path.with_name(self.db_path.name + ".markers.jsonl")
        database_files = [Path(str(self.db_path) + suffix) for suffix in ("", "-wal", "-shm", "-journal")]
        if any(marker.resolve() == path.resolve() or
               (marker.exists() and path.exists() and marker.samefile(path)) for path in database_files):
            raise ValueError("The marker log must be outside the database and its journal files")
        object.__setattr__(self, "marker_log_path", marker)

    @classmethod
    def from_env(cls):
        credential_directory = os.environ.get("CREDENTIALS_DIRECTORY")
        token = None
        if credential_directory:
            try:
                token = (Path(credential_directory) / "discord_token").read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                pass
        if token is None:
            token = os.environ.get("DISCORD_TOKEN", "").strip()
            if token:
                LOG.warning("Using DISCORD_TOKEN fallback; prefer systemd credentials")
        heartbeat = None
        if credential_directory:
            try:
                heartbeat = (Path(credential_directory) / "heartbeat_url").read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                pass
        if heartbeat is None:
            heartbeat = os.environ.get("POKEWALKER_HEARTBEAT_URL", "").strip()
            if heartbeat:
                LOG.warning("Using POKEWALKER_HEARTBEAT_URL fallback; prefer systemd credentials")
        owners = os.environ.get("POKEWALKER_OWNER_IDS", "").strip()
        dev_guild = os.environ.get("POKEWALKER_DEV_GUILD_ID", "").strip()
        override = os.environ.get("POKEWALKER_ALLOW_UNPATCHED_SQLITE", "0")
        if override not in {"0", "1"}:
            raise ValueError("POKEWALKER_ALLOW_UNPATCHED_SQLITE must be 0 or 1")
        return cls(Secret(token), Path(os.environ.get("POKEWALKER_DB_PATH", "pokewalker.sqlite3")),
                   Path(os.environ.get("POKEWALKER_CONTENT_PATH", "content/artifact/content.json")),
                   frozenset(snowflake(value.strip()) for value in owners.split(",")) if owners else frozenset(),
                   override == "1", snowflake(dev_guild) if dev_guild else None,
                   Path(os.environ["POKEWALKER_MARKER_LOG"]) if os.environ.get("POKEWALKER_MARKER_LOG") else None,
                   Path(os.environ["POKEWALKER_PRIVACY_PATH"]) if os.environ.get("POKEWALKER_PRIVACY_PATH") else None,
                   snowflake(os.environ["POKEWALKER_ADMIN_GUILD_ID"]) if os.environ.get("POKEWALKER_ADMIN_GUILD_ID") else None,
                   os.environ.get("POKEWALKER_RELEASE", "dev"), Secret(heartbeat) if heartbeat else None)
