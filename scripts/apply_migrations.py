"""Supabase CLI 없이 마이그레이션·시드 적용 (T6).

직접 Postgres(pooler, session 모드) 접속, 키·비밀번호 미출력.

- supabase/migrations/*.sql 을 이름순으로 적용, public._migrations 에 기록(멱등)
- --seed 로 supabase/seed.sql 실행
접속: SUPABASE_DB_PASSWORD + SUPABASE_DB_HOST(.env, 기본 aws-0-ap-northeast-1.pooler.supabase.com)
"""

from __future__ import annotations

import argparse
import sys

import psycopg

from algaecast.config import ROOT, get_env

REF = "rjfjqquvzgvijvvvnrgf"


def connect() -> psycopg.Connection:
    host = get_env("SUPABASE_DB_HOST", "aws-0-ap-northeast-1.pooler.supabase.com")
    return psycopg.connect(
        host=host,
        port=5432,
        dbname="postgres",
        user=f"postgres.{REF}",
        password=get_env("SUPABASE_DB_PASSWORD", required=True),
        sslmode="require",
        connect_timeout=15,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    mig_dir = ROOT / "supabase" / "migrations"
    files = sorted(mig_dir.glob("*.sql"))
    with connect() as conn:
        conn.execute(
            "create table if not exists public._migrations "
            "(name text primary key, applied_at timestamptz default now())"
        )
        done = {r[0] for r in conn.execute("select name from public._migrations").fetchall()}
        for f in files:
            if f.name in done:
                print(f"skip {f.name} (applied)")
                continue
            sql = f.read_text(encoding="utf-8")
            print(f"apply {f.name} ({len(sql):,} chars)")
            if not args.dry_run:
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute("insert into public._migrations (name) values (%s)", (f.name,))
        if args.seed:
            seed = (ROOT / "supabase" / "seed.sql").read_text(encoding="utf-8")
            print(f"seed ({len(seed):,} chars)")
            if not args.dry_run:
                conn.execute(seed)
        conn.commit()
        n = conn.execute(
            "select count(*) from information_schema.tables where table_schema='public'"
        ).fetchone()[0]
        print(f"public 테이블/뷰 수: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
