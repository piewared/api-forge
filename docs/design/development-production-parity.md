# Development/Production Parity

## Problem

A generated project runs against different infrastructure in development than
in production: SQLite or a local Compose Postgres instead of a managed
Postgres, a seeded Keycloak realm instead of a real IdP. Every place where the
development stack is *more permissive* than production is a place where a
defect passes locally and fails after deployment.

Three such gaps were closed. Each followed the same shape: the development
environment accepted something production rejects, so the failure surfaced late
and expensively.

## 1. SQLite silently ignores foreign keys

SQLite ships with foreign-key enforcement disabled. A schema's `FOREIGN KEY`
constraints are inert unless `PRAGMA foreign_keys=ON` is issued **per
connection**. Postgres enforces them unconditionally.

The unit suite ran entirely on in-memory SQLite without the pragma, so
referential-integrity violations — inserting a child row before its parent,
writing a dangling `user_id` — passed a green test suite and only failed
against real Postgres.

**Decision.** A single helper,
`src/app/core/services/database/sqlite_pragmas.py::enforce_sqlite_foreign_keys`,
registers a `connect` listener that issues the pragma. It is applied at every
engine-construction site: `DbSessionService` and the test fixtures in
`tests/fixtures/core.py`.

Why a connect listener rather than a connect argument: the pragma is
per-connection, so pooled and reconnected DBAPI handles must each receive it.

Why one shared helper rather than a line at each site: there were already two
duplicated engine constructions in the fixtures alone, and a third in the
runtime. A future engine that forgets the pragma silently reintroduces the
entire bug class.

The function is a no-op for non-SQLite engines and returns the engine, so it
composes as a wrapper around `create_engine(...)`.

**Consequence.** Enabling this immediately failed five existing tests that had
been asserting against unrepresentable database states. Those tests were
corrected to construct the parent rows they always implied. One test
(`test_identity_exists_but_user_missing_returns_500`) covered a *defensive*
branch guarding against a user row disappearing; since the schema now makes an
orphan row impossible, that condition is injected at the repository instead of
being faked in the database.

## 2. The dev Keycloak realm minted tokens its own API rejected

Keycloak puts only `account` in the `aud` claim of an access token unless the
client is given an audience mapper. The API validates `aud` against
`config.jwt.audiences`, which defaults to `api://default`.

The seeded `test-realm`/`test-client` had no mapper, so **every** token the dev
IdP produced was rejected by the dev API. The Bearer-JWT path could not be
exercised at all without overriding `JWT_AUDIENCE=account` — which is not what
a real deployment looks like, and which masked the fact that the path was
untested.

**Decision.** `KeycloakSetup.ensure_audience_mapper` adds an
`oidc-audience-mapper` to the seeded client, reading the expected audience from
the same `JWT_AUDIENCE` environment variable `config.yaml` interpolates, so the
realm and the API cannot drift.

It runs as its own step in `setup_all`, *not* inside `create_client`, because
`create_client` returns early when the client already exists. Realms seeded by
an earlier version of the script must be repaired in place; the operation is
idempotent.

## 3. `dev` had no `db` command group

`prod`, `k8s`, and `fly` each expose `db migrate`; `dev` did not. Local schema
work therefore meant invoking Alembic directly with a hand-built
`DATABASE_URL` — undocumented, easy to point at the wrong database, and the
source of documentation that promised commands the CLI never had.

**Decision.** `dev db` provides `migrate` and `url` only.

It deliberately does **not** reuse `DbRuntime`, the abstraction behind the other
targets. `DbRuntime` is Postgres-shaped: roles, superuser credentials,
port-forwards, backups. The development database has none of that and may be
SQLite. Forcing it through that port would mean implementing methods that
cannot work.

Instead, `src/cli/commands/db/local_url.py` owns the one genuinely new concern
— resolving the development database URL from `config.yaml` — and `dev db
migrate` hands the result to the same dialect-agnostic
`src/infra/postgres/migrations.py::run_migration` the other targets use.

Two constraints that module encodes:

- `load_config` reads the environment from `os.environ`, so
  `APP_ENVIRONMENT=development` is set for the duration of the load and then
  restored, letting one CLI process still load other environments.
- `database.connection_string` resolves the password from the environment or a
  secrets file, and now dispatches on dialect (see below), so it is safe to use
  for both SQLite and PostgreSQL projects.

## 4. `connection_string` assumed PostgreSQL

`use_postgres` defaults to **no**, so the default generated project runs on
SQLite (`post_gen_setup.py` rewrites `database.url` to
`sqlite:///./database.db`). But `DatabaseConfig.connection_string`
unconditionally rendered a `postgresql://` string, applying PostgreSQL-only
reconciliation — `user`, `app_db`, password resolution — to a URL that has none
of those concepts:

```
sqlite:///./database.db  ->  postgresql://user@None:None/app_db
```

`DbSessionService` passes that straight to `create_engine`, which raised
`ValueError: invalid literal for int() with base 10: 'None'`. The default
configuration could not build a database engine at all.

**Decision.** `connection_string` dispatches on dialect. `is_sqlite` keys off
`parsed_url.drivername`, so driver-qualified names like `sqlite+aiosqlite`
resolve correctly. The SQLite branch returns the configured URL verbatim — it
is already a valid SQLAlchemy URL — while the PostgreSQL branch is unchanged.

Relatedly, `DbSessionService._get_pool_kwargs` omits `pool_size` /
`max_overflow` / `pool_timeout` / `pool_recycle` for SQLite. SQLite picks its
pool implementation from the target database, and the in-memory pool
(`SingletonThreadPool`) rejects those server-oriented arguments with a
`TypeError` before the engine is built. Pool sizing is meaningless for a
single-writer local file in any case.

A now-deleted helper, `db_utils.get_database_url`, had a related defect: it
returned `str(base_url)`, and SQLAlchemy 2.0's `URL.__str__` **masks the
password**, so it produced URLs that could never connect. It had no callers and
was removed rather than repaired.

## 5. The configured driver is preserved

`_postgres_connection_string` also hardcoded the `postgresql://` scheme,
discarding any driver qualifier: a configured `postgresql+psycopg2://` was
silently rewritten to bare `postgresql://`, substituting SQLAlchemy's default
driver for the caller's explicit choice.

**Decision.** The rendered string keeps `base_url.drivername`. Dialect
decisions instead key off a new `backend_name` property
(`URL.get_backend_name()`), which strips the qualifier — `postgresql+psycopg2`
and `postgresql` are both the `postgresql` backend.

This surfaced two coupled defects:

- The production `search_path=app` option was gated on
  `drivername in ("postgresql", "postgres")`. Since the shipped default was
  `postgresql+asyncpg`, that test never matched, so **production never
  received `search_path=app`**. It is now gated on `backend_name`.
- The shipped default was an *async* driver, but the application uses
  synchronous SQLAlchemy/SQLModel sessions and depends on `psycopg2-binary`
  (`asyncpg` is not a dependency at all). Preserving the driver faithfully
  would therefore have broken startup with `ModuleNotFoundError: asyncpg` —
  the scheme rewrite had been masking a wrong default. The defaults in
  `config.yaml` and `DatabaseConfig.url` are now `postgresql://`.

`scripts/post_gen_setup.py` rewrites that default to SQLite when
`use_postgres=false` by regex; its pattern now accepts any `postgresql(+driver)?`
form so it cannot silently stop matching if the default driver changes again.

## Rule this establishes

The development environment must reject everything production rejects.
Permissiveness in a local stack is not convenience — it is deferred failure.
