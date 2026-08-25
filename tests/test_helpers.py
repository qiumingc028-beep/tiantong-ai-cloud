from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def latest_alembic_head() -> str:
    config = Config(str(Path("alembic.ini")))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert heads, "alembic head is empty"
    return heads[0]


def latest_alembic_head_line() -> str:
    return f"{latest_alembic_head()} (head)"
