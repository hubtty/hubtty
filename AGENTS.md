# AGENTS.md

## Setup

```
uv sync --dev
```

## Dev commands

```
uv run flake8       # lint (pyflakes only -- all style rules disabled)
uv run pytest       # tests
```

CI runs both flake8 and pytest.

## Architecture

Console-based GitHub code review TUI. Entrypoint: `hubtty/app.py:main`.

- `hubtty/sync/` -- GitHub API sync engine (http client, task queue, event handling). Tests in `tests/sync/`. See `hubtty/sync/README.md` for detailed architecture docs.
- `hubtty/view/` -- urwid TUI screens (repository list, PR list, PR detail, diffs)
- `hubtty/search/` -- PLY (lex/yacc) search query parser against local SQLite DB
- `hubtty/db.py` -- SQLAlchemy ORM models (all tables defined via `Table()` objects + classical mapping)
- `hubtty/alembic/` -- Alembic migrations. Config: `hubtty/alembic.ini` (inside the package, not repo root)
- `hubtty/config.py` -- YAML config loader (user config at `$XDG_CONFIG_HOME/hubtty/hubtty.yaml`)

## Style

New files should include the copyright header: `# Copyright The Hubtty Authors.`

Match existing code style. Flake8 config (`.flake8`) ignores all W/E rules -- only pyflakes errors matter. No auto-formatter enforced. Python >=3.10; `match/case` syntax is used.

## Database

SQLAlchemy classical mapping (not declarative). Tables defined in `db.py` with `Table()` objects, then mapped with `registry.map_imperatively()`. Alembic handles schema migrations.

## Tests

Tests live in `tests/`. Uses pytest with mock fixtures (`tests/sync/conftest.py`). No external services required.
