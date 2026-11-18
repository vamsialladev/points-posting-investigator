"""Alembic entry point. The shared logic, including SET ROLE to the owner, is app.db.migrate.run_env."""

from app.db.migrate import run_env

run_env()
