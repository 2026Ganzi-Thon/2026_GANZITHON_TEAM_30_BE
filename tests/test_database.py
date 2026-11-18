from app.config import normalize_database_url


def test_postgres_urls_use_psycopg_driver():
    assert normalize_database_url("postgres://u:p@localhost:5432/db") == "postgresql+psycopg://u:p@localhost:5432/db"
    assert normalize_database_url("postgresql://u:p@127.0.0.1/db") == "postgresql+psycopg://u:p@127.0.0.1/db"
    assert normalize_database_url("postgresql+psycopg://u:p@localhost/db") == "postgresql+psycopg://u:p@localhost/db"
    assert normalize_database_url("sqlite:///./ganzithon.db") == "sqlite:///./ganzithon.db"


def test_remote_postgres_requires_ssl():
    neon = "postgresql://owner:pw@ep-x-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb"
    assert normalize_database_url(neon) == "postgresql+psycopg://owner:pw@ep-x-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
    kept = neon + "?sslmode=require&channel_binding=require"
    assert normalize_database_url(kept).endswith("?sslmode=require&channel_binding=require")
    assert normalize_database_url(neon + "?application_name=ondo").endswith("?application_name=ondo&sslmode=require")
    assert normalize_database_url("postgresql://u:p@db.internal:5432/x").endswith("?sslmode=require")
