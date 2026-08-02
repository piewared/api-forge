# Design Documentation

Architectural decisions and rationale for the API Forge template. These
documents explain *why* the code is shaped the way it is; they are not a
restatement of the code itself.

For task-oriented guides (deployment, auth flows, migrations), see the parent
[`docs/`](../index.md) directory.

## Documents

| Document | Covers |
|----------|--------|
| [Development/production parity](development-production-parity.md) | Why the dev environment must reject what production rejects: SQLite foreign-key enforcement, dev-realm token audience, and the `dev db` command group. |
