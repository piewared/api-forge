# API Forge Documentation

API Forge is a production-ready **FastAPI template** designed for building secure, scalable backend services with built-in authentication, Docker development environment, and Kubernetes deployment support. This FastAPI starter includes PostgreSQL with SQLModel, Redis caching, Temporal workflows, OIDC authentication with BFF pattern, and comprehensive testing infrastructure.

## What is API Forge?

API Forge provides a complete foundation for FastAPI production applications with:

- **OIDC Authentication & BFF Pattern** - Session-based auth with Google, Microsoft, and Keycloak providers
- **PostgreSQL + SQLModel** - Type-safe ORM with SQLAlchemy under the hood
- **Redis Integration** - Caching, session storage, and rate limiting
- **Temporal Workflows** - Distributed workflow orchestration for async tasks
- **Docker Dev Environment** - Full local stack with PostgreSQL, Redis, Temporal, and Keycloak
- **Kubernetes Ready** - Production manifests with secrets, TLS, and mTLS support
- **Clean Architecture** - Separation of entities, repositories, services, and API layers
- **Comprehensive Testing** - Unit, integration, and E2E tests with pytest

## Who is This For?

API Forge is designed for Python developers who need to:

- Build production FastAPI applications without starting from scratch
- Implement secure authentication patterns with OIDC providers
- Deploy to Docker Compose or Kubernetes environments
- Use Temporal for background jobs and distributed workflows
- Follow clean architecture principles with type safety

## Core Stack

- **FastAPI 0.116+** - Modern Python web framework with automatic OpenAPI docs
- **Python 3.13+** - Latest Python with improved performance
- **SQLModel 0.0.24+** - Pydantic models that are also SQLAlchemy models
- **PostgreSQL** - Production database (SQLite for development)
- **Redis** - Caching, sessions, and rate limiting
- **Temporal** - Workflow orchestration engine
- **Docker & Kubernetes** - Containerized deployment options
- **uv** - Fast Python package manager

## Quick Start

```bash
# Install copier
uv tool install copier

# Generate a new project
copier copy gh:piewared/api-forge my-project

# Start development environment
cd my-project
cp .env.example .env
uv sync
uv run api-forge-cli deploy up dev

# Run the application
uvicorn src_main:app --reload
```

Visit http://localhost:8000/docs for interactive API documentation.

## Documentation Guide

### Getting Started

- **[Docker Dev Environment](./fastapi-docker-dev-environment.md)** - Set up local development with Docker Compose
- **[Testing Strategy](./fastapi-testing-strategy.md)** - Run unit and integration tests with pytest

### Authentication & Security

- **[OIDC Authentication & BFF Pattern](./fastapi-auth-oidc-bff.md)** - Session-based auth with OIDC providers
- **[Sessions and Cookies](./fastapi-sessions-and-cookies.md)** - Cookie security, CSRF protection, and client fingerprinting

### Architecture & Design

- **[Clean Architecture Overview](./fastapi-clean-architecture-overview.md)** - Entities, repositories, services, and API layers
- **[Temporal Workflows](./fastapi-temporal-workflows.md)** - Background jobs and distributed workflows

### Deployment

- **[Kubernetes Deployment](./fastapi-kubernetes-deployment.md)** - Deploy to production Kubernetes
- **[Docker Compose Production](./fastapi-production-deployment-docker-compose.md)** - Deploy with Docker Compose, TLS, and mTLS
- **[Secret Rotation](./secret-rotation.md)** - Automated secret rotation with zero-downtime redeployment

### Client Examples

- **[Python OIDC Client](./examples-python-oidc-client.md)** - Build Python clients that authenticate with your API
- **[JavaScript OIDC Client](./examples-javascript-oidc-client.md)** - Build web applications that integrate with your API

## Project Structure

```
my-project/
├── my_project/              # Main application package
│   ├── app/
│   │   ├── api/http/        # FastAPI routes and dependencies
│   │   ├── core/            # Auth, DB, config, security
│   │   ├── entities/        # Domain entities (generated)
│   │   ├── runtime/         # Config loading and initialization
│   │   ├── service/         # Application services
│   │   └── worker/          # Temporal activities and workflows
│   └── worker/              # Worker entrypoint
├── tests/                   # Unit and integration tests
├── k8s/                     # Kubernetes manifests
├── docker/                  # Docker configurations
├── infra/                   # Infrastructure scripts and secrets
├── config.yaml              # Application configuration
├── src_main.py              # Application entrypoint
└── pyproject.toml           # Dependencies and tooling
```

## Key Features

### OIDC Authentication with BFF Pattern

API Forge implements the Backend-for-Frontend (BFF) pattern for web authentication:

- Secure, HttpOnly session cookies
- CSRF protection with double-submit tokens
- Client fingerprinting for session security
- Support for multiple OIDC providers (Google, Microsoft, Keycloak)
- Automatic token refresh and session rotation

[Learn more about authentication →](./fastapi-auth-oidc-bff.md)

### Docker Development Environment

Complete local development stack with one command:

```bash
uv run api-forge-cli deploy up dev
```

Includes:
- PostgreSQL (port 5433)
- Redis (port 6380)
- Temporal server + UI (port 8082)
- Keycloak (port 8080) with pre-configured test users

[Set up development environment →](./fastapi-docker-dev-environment.md)

### Clean Architecture

Separation of concerns with clear boundaries:

- **Entities** - Domain models with business logic
- **Repositories** - Data access layer
- **Services** - Application business logic
- **API** - HTTP handlers and dependencies

[Understand the architecture →](./fastapi-clean-architecture-overview.md)

### Kubernetes Deployment

Production-ready Kubernetes manifests with:

- Secrets management via external secrets
- TLS/mTLS for service communication
- Horizontal pod autoscaling
- NetworkPolicies for security
- Health checks and readiness probes

[Deploy to Kubernetes →](./fastapi-kubernetes-deployment.md)

### Database Migrations

Integrated Alembic migrations with automatic model discovery:

- Auto-detects all SQLModel tables
- Port-forwarding support for Kubernetes PostgreSQL
- CLI integration for bundled and external databases
- Autogeneration from model changes
- Production-safe rollback support

[Manage database migrations →](./database-migrations.md)

### Temporal Workflows

Built-in support for distributed workflows:

- Activity and workflow definitions
- Automatic worker discovery
- Multiple task queues
- Retry policies and error handling

[Use Temporal workflows →](./fastapi-temporal-workflows.md)

## CLI Commands

API Forge includes a CLI for common development tasks:

```bash
# Development environment
uv run api-forge-cli deploy up dev       # Start Docker services
uv run api-forge-cli deploy down dev     # Stop services
uv run api-forge-cli deploy status dev   # Check service status
uvicorn src_main:app --reload           # Start FastAPI server

# Database migrations
uv run api-forge-cli k8s db migrate upgrade             # Apply migrations
uv run api-forge-cli k8s db migrate revision "message"  # Create migration
uv run api-forge-cli k8s db migrate current             # Show current state
uv run api-forge-cli k8s db migrate history             # View history

# Entity generation
uv run api-forge-cli entity add User     # Generate entity scaffold
uv run api-forge-cli entity list         # List entities

# Deployment
uv run api-forge-cli deploy up k8s       # Deploy to Kubernetes
uv run api-forge-cli deploy down k8s     # Remove from Kubernetes
uv run api-forge-cli deploy rotate k8s   # Rotate secrets and redeploy
```

## Testing

Run tests with pytest:

```bash
# All tests
uv run pytest

# Unit tests only
uv run pytest tests/unit/

# Integration tests (requires Docker services)
uv run pytest tests/integration/

# With coverage
uv run pytest --cov=my_project
```

[Learn about testing →](./fastapi-testing-strategy.md)

## Configuration

Configuration is managed via `config.yaml` with environment variable substitution:

```yaml
app:
  name: ${APP_NAME:-My API}
  environment: ${APP_ENVIRONMENT:-development}
  
database:
  url: ${DATABASE_URL:-sqlite:///database.db}
  
redis:
  url: ${REDIS_URL:-redis://localhost:6379/0}
  
oidc:
  providers:
    google:
      enabled: true
      client_id: ${OIDC_GOOGLE_CLIENT_ID}
```

Environment-specific overrides are automatically applied based on `APP_ENVIRONMENT`.

## Community & Support

- **GitHub**: [piewared/api-forge](https://github.com/piewared/api-forge)
- **Issues**: [Report bugs and request features](https://github.com/piewared/api-forge/issues)
- **Discussions**: [Ask questions and share ideas](https://github.com/piewared/api-forge/discussions)

## License

MIT License - see [LICENSE](../LICENSE) for details.

## Next Steps

1. **[Set up your development environment](./fastapi-docker-dev-environment.md)**
2. **[Understand authentication](./fastapi-auth-oidc-bff.md)**
3. **[Explore the architecture](./fastapi-clean-architecture-overview.md)**
4. **[Manage database migrations](./database-migrations.md)**
5. **[Deploy to production](./fastapi-kubernetes-deployment.md)**
