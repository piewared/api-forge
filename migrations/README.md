# Database Migrations

This directory contains Alembic database migration scripts for managing schema changes.

## Overview

- **Tool**: Alembic (SQLAlchemy migration tool)
- **Models**: SQLModel (based on SQLAlchemy)
- **Configuration**: `alembic.ini` (project root)
- **Environment**: `migrations/env.py`
- **Migration Scripts**: `migrations/versions/`

## Usage

All migration commands are integrated into the CLI and automatically handle port-forwarding for Kubernetes deployments.

### Apply Migrations

```bash
# Apply all pending migrations
uv run api-forge-cli k8s db migrate upgrade

# Apply up to a specific revision
uv run api-forge-cli k8s db migrate upgrade abc123
```

### Create New Migration

```bash
# Auto-generate migration from model changes (recommended)
uv run api-forge-cli k8s db migrate revision "add user table"

# Create empty migration template for manual changes
uv run api-forge-cli k8s db migrate revision "custom changes" --no-autogenerate
```

### Rollback Migrations

```bash
# Rollback to a specific revision
uv run api-forge-cli k8s db migrate downgrade abc123

# Rollback one migration
uv run api-forge-cli k8s db migrate downgrade -1

# Rollback all migrations (to base)
uv run api-forge-cli k8s db migrate downgrade base
```

### View Migration State

```bash
# Show current migration revision
uv run api-forge-cli k8s db migrate current

# Show full migration history
uv run api-forge-cli k8s db migrate history
```

### Generate SQL (Dry Run)

```bash
# See what SQL would be executed without running it
uv run api-forge-cli k8s db migrate upgrade --sql
uv run api-forge-cli k8s db migrate downgrade abc123 --sql
```

## Workflow

### 1. Make Model Changes

Edit your SQLModel models in `src/app/entities/`:

```python
# src/app/entities/user/models.py
from sqlmodel import Field, SQLModel

class User(SQLModel, table=True):
    id: int = Field(primary_key=True)
    email: str = Field(unique=True, index=True)
    name: str
    # Add new field:
    is_active: bool = Field(default=True)
```

### 2. Import Models in env.py

Ensure your models are imported in `migrations/env.py` so Alembic can detect them:

```python
# In migrations/env.py, add:
from src.app.entities.user.models import User
from src.app.entities.book.models import Book
# ... import all your models
```

### 3. Generate Migration

```bash
uv run api-forge-cli k8s db migrate revision "add user is_active field"
```

This will:
- Compare your models to the current database schema
- Generate a migration file in `migrations/versions/`
- Include upgrade() and downgrade() functions

### 4. Review Migration

Check the generated file in `migrations/versions/YYYYMMDD_HHMM_slug.py`:

```python
def upgrade() -> None:
    op.add_column('user', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))

def downgrade() -> None:
    op.drop_column('user', 'is_active')
```

Edit if needed (add data migrations, custom logic, etc.)

### 5. Apply Migration

```bash
uv run api-forge-cli k8s db migrate upgrade
```

### 6. Verify

```bash
uv run api-forge-cli k8s db migrate current
uv run api-forge-cli k8s db verify
```

## Best Practices

1. **Always review auto-generated migrations** - Alembic might not perfectly detect all changes
2. **Test migrations locally first** - Use a dev environment before production
3. **Keep migrations small and focused** - One logical change per migration
4. **Never edit applied migrations** - Create new migrations for changes
5. **Use meaningful names** - Describe what the migration does
6. **Handle data migrations carefully** - Consider downtime and large datasets
7. **Backup before major migrations** - Use `k8s db backup` first

## Integration with Kubernetes

The CLI automatically:
- Establishes port-forwarding to the PostgreSQL pod
- Loads database credentials from secrets
- Handles both bundled and external databases
- Works in any namespace/environment

## Troubleshooting

### "Target database is not up to date"

```bash
# Check current state
uv run api-forge-cli k8s db migrate current

# Apply pending migrations
uv run api-forge-cli k8s db migrate upgrade
```

### "Can't locate revision identified by 'abc123'"

The revision doesn't exist. Check available revisions:

```bash
uv run api-forge-cli k8s db migrate history
```

### Auto-generation not detecting changes

Ensure your models are imported in `migrations/env.py`:

```python
# Add at top of migrations/env.py
from src.app.entities.user.models import User
from src.app.entities.book.models import Book
# ... all models that should be tracked
```

### Migration conflicts

If multiple developers create migrations simultaneously:

```bash
# Merge migration branches
alembic merge -m "merge branches" head1 head2

# Or manually edit migration to depend on both
```

## Migration File Structure

```
migrations/
├── env.py              # Alembic environment configuration
├── script.py.mako      # Template for new migrations
└── versions/           # Migration scripts
    ├── 20231201_1430_initial_schema.py
    ├── 20231202_0900_add_user_table.py
    └── 20231203_1600_add_indexes.py
```

## Production Deployment

Include migration in your deployment pipeline:

```bash
# 1. Backup database
uv run api-forge-cli k8s db backup

# 2. Apply migrations
uv run api-forge-cli k8s db migrate upgrade

# 3. Verify
uv run api-forge-cli k8s db verify

# 4. Deploy application
uv run api-forge-cli deploy up k8s
```

## Further Reading

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLModel Documentation](https://sqlmodel.tiangolo.com/)
- [Migration Best Practices](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
