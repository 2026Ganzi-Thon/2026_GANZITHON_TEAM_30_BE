from app.config import normalize_database_url


def test_render_postgres_urls_use_psycopg_driver():
    assert normalize_database_url("postgres://u:p@host:5432/db") == "postgresql+psycopg://u:p@host:5432/db"
    assert normalize_database_url("postgresql://u:p@host/db") == "postgresql+psycopg://u:p@host/db"
    assert normalize_database_url("postgresql+psycopg://u:p@host/db") == "postgresql+psycopg://u:p@host/db"
    assert normalize_database_url("sqlite:///./ganzithon.db") == "sqlite:///./ganzithon.db"


def test_supabase_urls_require_ssl():
    pooler = "postgresql://postgres.abc:pw@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"
    assert normalize_database_url(pooler).endswith(":5432/postgres?sslmode=require")
    assert normalize_database_url(pooler + "?sslmode=verify-full").endswith("?sslmode=verify-full")
    assert normalize_database_url(pooler + "?application_name=ondo").endswith("?application_name=ondo&sslmode=require")
