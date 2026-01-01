# Database Migrations Guide

This guide covers database schema migrations using Alembic, integrated into the API Forge CLI for both bundled and external PostgreSQL deployments.

## Overview

API Forge uses **Alembic** for database schema migrations with automatic model discovery from SQLModel table definitions. The system:

- **Auto-discovers** all SQLModel tables - no manual import lists to maintain
- **Handles port-forwarding** automatically for bundled Kubernetes PostgreSQL
- **Supports both** bundled (in-cluster) and external PostgreSQL databases
- **Integrates** with the CLI for a seamless workflow

## Architecture

### Components

- **`alembic.ini`** - Alembic configuration file (project root)
- **`migrations/env.py`** - Migration environment with dynamic model discovery
- **`migrations/versions/`** - Individual migration scripts
- **`src/app/entities/loader.py`** - Dynamic table discovery using `SQLModel.metadata`
- **CLI commands** - `uv run api-forge-cli k8s db migrate ...`

### How It Works

1. **Model Registration**: All SQLModel classes with `table=True` automatically register with `SQLModel.metadata` when imported
2. **Dynamic Discovery**: `src/app/entities/loader.py` uses `rglob("table.py")` to find all table modules and imports them
3. **Autogeneration**: Alembic compares `SQLModel.metadata` (your models) against the database schema to detect changes
4. **Port-Forwarding**: CLI automatically establishes `kubectl port-forward` for bundled PostgreSQL before running Alembic

## Quick Start

### 1. Create Your First Migration

After defining your SQLModel tables:

```bash
# Auto-generate migration from model changes
uv run api-forge-cli k8s db migrate revision "initial schema" --autogenerate
```

This will:
- Scan all `table.py` files in `src/app/entities/`
- Compare models against the database schema
- Generate a migration file in `migrations/versions/`

### 2. Review the Generated Migration

```bash
# Check what was generated
cat migrations/versions/2025*_initial_schema.py
```

Review the `upgrade()` and `downgrade()` functions to ensure correctness.

### 3. Apply the Migration

```bash
# Apply to database
uv run api-forge-cli k8s db migrate upgrade
```

### 4. Verify

```bash
# Check current migration state
uv run api-forge-cli k8s db migrate current
```

## CLI Commands

All commands work with both bundled and external PostgreSQL.

### Create Migrations

```bash
# Auto-generate from model changes (recommended)
uv run api-forge-cli k8s db migrate revision "add user email" --autogenerate

# Create empty template for manual SQL
uv run api-forge-cli k8s db migrate revision "custom index" --no-autogenerate

# Generate SQL without applying
uv run api-forge-cli k8s db migrate upgrade --sql > migration.sql
```

### Apply Migrations

```bash
# Apply all pending migrations
uv run api-forge-cli k8s db migrate upgrade

# Apply to specific revision
uv run api-forge-cli k8s db migrate upgrade abc123

# Apply one migration at a time
uv run api-forge-cli k8s db migrate upgrade +1
```

### Rollback Migrations

```bash
# Rollback to specific revision
uv run api-forge-cli k8s db migrate downgrade abc123

# Rollback one migration
uv run api-forge-cli k8s db migrate downgrade -1

# Rollback all (to empty database)
uv run api-forge-cli k8s db migrate downgrade base

# Generate rollback SQL without applying
uv run api-forge-cli k8s db migrate downgrade -1 --sql > rollback.sql
```

### View Migration State

```bash
# Show current migration version
uv run api-forge-cli k8s db migrate current

# Show current head revision(s)
uv run api-forge-cli k8s db migrate heads

# Show a specific migration's details
uv run api-forge-cli k8s db migrate show 19becf30b774

# Show all migrations
uv run api-forge-cli k8s db migrate history

# Show detailed history with verbose flag
uv run api-forge-cli k8s db migrate history --verbose
```

### Team Workflows (Multiple Heads)

When multiple developers generate migrations in parallel, Alembic can end up with
multiple heads. These commands help resolve that cleanly.

```bash
# View current heads
uv run api-forge-cli k8s db migrate heads

# Merge all current heads into a single head
uv run api-forge-cli k8s db migrate merge --message "merge heads"

# Merge specific revisions
uv run api-forge-cli k8s db migrate merge --message "merge" -r abc123 -r def456
```

### Stamping (Baseline / Repair)

`stamp` sets the database's Alembic revision *without* running migrations.
This is useful for baselining an existing database or repairing the version table.

```bash
# Mark DB as up-to-date with the latest migration
uv run api-forge-cli k8s db migrate stamp head

# Mark DB as a specific revision
uv run api-forge-cli k8s db migrate stamp 19becf30b774
```

## Development Workflow

### Adding a New Entity

When you add a new entity to your application:

1. **Create the table model** in `src/app/entities/<domain>/<entity>/table.py`:

```python
from sqlmodel import Field
from src.app.entities.core._base import EntityTable

class ProductTable(EntityTable, table=True):
    """Product table model."""
    
    name: str = Field(max_length=255)
    price: float = Field(gt=0)
    sku: str = Field(max_length=100, index=True)
```

2. **Generate migration** (auto-detected, no imports needed):

```bash
uv run api-forge-cli k8s db migrate revision "add product table" --autogenerate
```

3. **Review** the generated migration file

4. **Apply** to database:

```bash
uv run api-forge-cli k8s db migrate upgrade
```

That's it! The dynamic loader finds your new `table.py` automatically.

### Modifying Existing Tables

1. **Update the table model** in `src/app/entities/<domain>/<entity>/table.py`:

```python
class UserTable(EntityTable, table=True):
    # ... existing fields ...
    
    # Add new field
    phone_number: str | None = Field(default=None, max_length=20)
```

2. **Generate migration**:

```bash
uv run api-forge-cli k8s db migrate revision "add user phone number" --autogenerate
```

3. **Review and apply**:

```bash
cat migrations/versions/*_add_user_phone_number.py
uv run api-forge-cli k8s db migrate upgrade
```

### Testing Migrations

Before applying to production:

1. **Apply migration** in development/staging:

```bash
uv run api-forge-cli k8s db migrate upgrade
```

2. **Test the application** with the new schema

3. **Test rollback**:

```bash
uv run api-forge-cli k8s db migrate downgrade -1
# Verify app still works
uv run api-forge-cli k8s db migrate upgrade
```

## Best Practices

### 1. Always Use Autogenerate

Let Alembic detect changes automatically:

```bash
# ✅ Recommended
uv run api-forge-cli k8s db migrate revision "add column" --autogenerate

# ❌ Avoid (unless you need custom SQL)
uv run api-forge-cli k8s db migrate revision "add column" --no-autogenerate
```

### 2. Review Generated Migrations

Alembic may not always generate perfect migrations. Always review:

```python
def upgrade() -> None:
    # Check for:
    # - Correct column types
    # - Proper null/default handling
    # - Index creation
    # - Foreign key constraints
    op.add_column('users', sa.Column('email', sa.String(255), nullable=True))
    # Add data migration if needed
    op.execute("UPDATE users SET email = concat(username, '@example.com')")
    # Then enforce constraint
    op.alter_column('users', 'email', nullable=False)
```

### 3. Write Reversible Migrations

Always implement proper `downgrade()`:

```python
def upgrade() -> None:
    op.add_column('users', sa.Column('status', sa.String(20)))

def downgrade() -> None:
    op.drop_column('users', 'status')
```

### 4. Test Migrations Before Deploying

```bash
# Apply migration
uv run api-forge-cli k8s db migrate upgrade

# Test app functionality

# Test rollback
uv run api-forge-cli k8s db migrate downgrade -1

# Test app still works

# Re-apply
uv run api-forge-cli k8s db migrate upgrade
```

### 5. Handle Data Migrations Carefully

For operations that modify existing data:

```python
def upgrade() -> None:
    # 1. Add column as nullable
    op.add_column('products', sa.Column('category', sa.String(50), nullable=True))
    
    # 2. Populate data
    op.execute("""
        UPDATE products 
        SET category = 'general' 
        WHERE category IS NULL
    """)
    
    # 3. Make non-nullable
    op.alter_column('products', 'category', nullable=False)
```

### 6. Never Edit Applied Migrations

Once a migration is applied to any environment (dev, staging, prod):

- ❌ Never edit it
- ✅ Create a new migration to fix issues

### 7. Keep Migrations Small

- One logical change per migration
- Makes rollback easier
- Simplifies code review

```bash
# ✅ Good - focused migrations
uv run api-forge-cli k8s db migrate revision "add user email"
uv run api-forge-cli k8s db migrate revision "add email index"

# ❌ Bad - too many changes
uv run api-forge-cli k8s db migrate revision "update user schema"
```

## Production Deployment

### Pre-Deployment

1. **Generate migration** in development:

```bash
uv run api-forge-cli k8s db migrate revision "production change" --autogenerate
```

2. **Test thoroughly** in staging environment

3. **Commit migration file** to version control

### Deployment Process

1. **Backup database**:

```bash
kubectl exec -n api-forge-prod postgresql-0 -- pg_dump -U postgres appdb > backup.sql
```

2. **Apply migration**:

```bash
uv run api-forge-cli k8s db migrate upgrade
```

3. **Verify**:

```bash
uv run api-forge-cli k8s db migrate current
uv run api-forge-cli k8s db verify
```

4. **Deploy application** with new code

### Rollback Plan

If issues occur:

```bash
# 1. Rollback application deployment
kubectl rollout undo deployment/api-forge -n api-forge-prod

# 2. Rollback migration
uv run api-forge-cli k8s db migrate downgrade -1

# 3. Verify
uv run api-forge-cli k8s db verify
```

## Troubleshooting

### Migration Fails with "target database has pending upgrade operations"

**Cause**: Previous migration was interrupted

**Solution**:
```bash
# Check current state
uv run api-forge-cli k8s db migrate current

# Force to specific revision
uv run api-forge-cli k8s db migrate upgrade abc123
```

### Alembic Can't Detect My New Table

**Cause**: Table model not being imported

**Solution**: Verify your `table.py` file exists in `src/app/entities/`:

```bash
# Should list your table.py files
find src/app/entities -name "table.py"

# Test import
uv run python -c "from src.app.entities.loader import get_metadata; print(get_metadata().tables.keys())"
```

### Port-Forward Connection Error

**Cause**: Bundled PostgreSQL pod not ready

**Solution**:
```bash
# Check pod status
kubectl get pods -n api-forge-prod -l app=postgresql

# Restart port-forward by retrying command
uv run api-forge-cli k8s db migrate current
```

### Schema Drift Detected

**Cause**: Manual changes made to database outside migrations

**Solution**:
```bash
# Generate migration to align
uv run api-forge-cli k8s db migrate revision "fix schema drift" --autogenerate

# Review carefully - may need manual editing
cat migrations/versions/*_fix_schema_drift.py
```

### Multiple Heads Detected

**Cause**: Branches in migration history (multiple developers)

**Solution**:
```bash
# View heads
uv run api-forge-cli k8s db migrate heads

# Merge branches
uv run api-forge-cli k8s db migrate revision "merge branches" --merge
```

## Advanced Topics

### Branching and Merging

For teams working on multiple features:

```bash
# Create branch label
uv run api-forge-cli k8s db migrate revision "feature a" --autogenerate --branch-label feature_a

# Create another branch
uv run api-forge-cli k8s db migrate revision "feature b" --autogenerate --branch-label feature_b

# Merge branches
uv run api-forge-cli k8s db migrate revision "merge features" --merge
```

### Custom SQL Migrations

For complex operations not detectable by autogenerate:

```bash
# Create empty template
uv run api-forge-cli k8s db migrate revision "optimize indexes" --no-autogenerate
```

Edit the generated file:

```python
def upgrade() -> None:
    # Custom SQL
    op.execute("""
        CREATE INDEX CONCURRENTLY idx_users_email_lower 
        ON users (LOWER(email))
    """)

def downgrade() -> None:
    op.execute("DROP INDEX idx_users_email_lower")
```

### Offline SQL Generation

Generate SQL without database connection:

```bash
# Generate upgrade SQL
uv run api-forge-cli k8s db migrate upgrade --sql > upgrade.sql

# Apply manually
psql -h localhost -U postgres appdb < upgrade.sql
```

## Reference

### Environment Variables

Set by CLI automatically, but available for manual use:

- `DATABASE_URL` - Complete PostgreSQL connection string (set by CLI)

### File Structure

```
project/
├── alembic.ini                          # Alembic config
├── migrations/
│   ├── env.py                           # Migration environment
│   ├── script.py.mako                   # Migration template
│   ├── README.md                        # Technical reference
│   └── versions/                        # Migration scripts
│       └── 20251224_0327_initial.py
└── src/
    └── app/
        └── entities/
            ├── loader.py                # Dynamic table discovery
            └── core/
                └── user/
                    └── table.py         # User table model
```

### Related Documentation

- [PostgreSQL Configuration](postgres/configuration.md)
- [Kubernetes Database Management](fastapi-kubernetes-deployment.md)
- [Production Deployment](infra/PRODUCTION_DEPLOYMENT.md)
- [Database Security](postgres/security.md)

## Getting Help

If you encounter issues:

1. Check this guide's **Troubleshooting** section
2. Review `migrations/README.md` for technical details
3. Check Alembic logs for detailed error messages
4. Verify database connectivity: `uv run api-forge-cli k8s db verify`

For Alembic-specific documentation: https://alembic.sqlalchemy.org/
