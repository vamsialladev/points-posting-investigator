"""Role names, URLs and grant statements, offline. The real-database checks are in test_ledger_postgres.py."""

import pytest
from psycopg import sql

from app.db.bootstrap import conninfo, grant_statements
from app.db.migrate import TREES, alembic_config
from app.db.roles import PASSWORD_VARIABLES, RUNTIME_ROLES, Database, loopback, runtime_url
from app.ledger.schema import metadata as ledger_metadata
from app.pipeline.tables import metadata as posting_metadata


def test_names_and_prefixes():
    db = Database("ledger", "test_")
    assert (db.name, db.owner, db.runtime) == ("test_ledger", "test_ledger_owner", "test_ledger_app")
    assert db.password_variable == "LEDGER_DB_PASSWORD"
    assert Database("posting").name == "posting"


@pytest.mark.parametrize("prefix", ["Test_", "x;drop", "a-b", "a" * 17])
def test_a_prefix_cannot_inject_sql(prefix):
    with pytest.raises(ValueError):
        Database("ledger", prefix)


def test_unknown_databases_are_refused():
    with pytest.raises(ValueError):
        Database("everything")


def test_the_runtime_url_keeps_its_password_out_of_text():
    url = runtime_url(Database("ledger"), "fake-db-password", host="db", port=5433)
    assert (url.username, url.host, url.port, url.database) == ("ledger_app", "db", 5433, "ledger")
    assert url.query["connect_timeout"] == "10"
    assert url.password == "fake-db-password"
    assert "fake-db-password" not in str(url) and "fake-db-password" not in repr(url)


def test_conninfo_falls_back_to_local_defaults():
    url = runtime_url(Database("ledger"), "fake-db-password")
    info = conninfo(url, "other")
    assert (info["host"], info["port"], info["dbname"], info["user"]) == ("127.0.0.1", 5432, "other", "ledger_app")
    assert info["connect_timeout"] == 10  # a connection fails within 10 s; it never hangs


@pytest.mark.parametrize(("host", "expected"), [("localhost", "127.0.0.1"), (None, "127.0.0.1"), ("db", "db")])
def test_localhost_means_ipv4(host, expected):
    # Windows resolves localhost to ::1 first, and Docker Desktop accepted ::1 then never answered: the first
    # integration run hung for 10 minutes (verification log, M2).
    assert loopback(host) == expected


def grants(base: str, suffix: str) -> dict[str, str]:
    return next(role.grants for role in RUNTIME_ROLES[base] if role.suffix == suffix)


def test_every_table_has_listed_rights_and_nothing_else_is_granted():
    """A new table nobody may use is a mistake; a grant on a table that doesn't exist is a typo."""
    for base, metadata in (("ledger", ledger_metadata), ("posting", posting_metadata)):
        granted = {
            obj.split(" ", 1)[1] for role in RUNTIME_ROLES[base] for obj in role.grants if obj.startswith("TABLE ")
        }
        assert granted == set(metadata.tables), base


def test_the_ledger_runtime_role_can_never_update_or_delete():
    assert grants("ledger", "app")["TABLE credits"] == "SELECT, INSERT"


def test_the_posting_service_never_changes_an_outbox_row_and_the_relay_never_writes_one():
    assert grants("posting", "app")["TABLE outbox"] == "SELECT, INSERT"  # ADR-0014: marking is the relay's job
    relay = grants("posting", "relay")
    assert set(relay) == {"TABLE outbox"}  # no access to the posting table at all
    assert relay["TABLE outbox"].startswith("SELECT, UPDATE (") and "INSERT" not in relay["TABLE outbox"]
    for column in ("payload", "topic", "message_key", "headers", "trace_context", "created_at"):
        assert column not in relay["TABLE outbox"]


def test_every_runtime_role_has_its_own_password_variable():
    assert PASSWORD_VARIABLES == ("LEDGER_DB_PASSWORD", "POSTING_DB_PASSWORD", "RELAY_DB_PASSWORD", "OPS_DB_PASSWORD")
    assert Database("posting", "test_").role_name("relay") == "test_posting_relay"
    with pytest.raises(ValueError):
        Database("ledger").role_name("relay")


def test_grants_are_revoke_then_grant_for_each_object_and_role():
    statements = grant_statements(Database("posting", "test_"))
    rendered = [s.as_string(None) for s in statements]
    assert len(rendered) == 2 * sum(len(role.grants) for role in RUNTIME_ROLES["posting"])
    assert rendered[0] == 'REVOKE ALL ON TABLE "posting" FROM "test_posting_app"'
    assert rendered[1] == 'GRANT SELECT, INSERT ON TABLE "posting" TO "test_posting_app"'
    assert rendered[-2] == 'REVOKE ALL ON TABLE "outbox" FROM "test_posting_relay"'
    assert all(isinstance(s, sql.Composed) for s in statements)


def test_each_database_has_a_migration_tree_matching_its_tables():
    assert set(TREES) == set(RUNTIME_ROLES)
    for base, (location, _) in TREES.items():
        assert (location / "env.py").exists() and list((location / "versions").glob("*.py")), base


def test_alembic_runs_as_the_owner_with_the_url_as_an_object():
    url = runtime_url(Database("ledger"), "fake-db-password")
    config = alembic_config(url, Database("ledger", "test_"))
    assert config.attributes["role"] == "test_ledger_owner"
    assert config.attributes["url"].database == "test_ledger"
    assert config.get_main_option("sqlalchemy.url") is None  # no password in an ini option
