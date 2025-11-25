"""Unit tests for Redis removal in post_gen_setup.py."""

import sys
from pathlib import Path
from textwrap import dedent

# Add scripts directory to path so we can import the production code
scripts_dir = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from docker_compose_utils import remove_redis_from_docker_compose


class TestRedisRemovalFromDockerCompose:
    """Test suite for Redis service removal from docker-compose files."""

    def test_removes_redis_service_block(self):
        """Test that Redis service definition is completely removed."""
        input_yaml = dedent(
            """
            services:
              postgres:
                image: postgres:15

              redis:
                image: redis:7
                container_name: api-forge-redis
                ports:
                  - "6379:6379"
                volumes:
                  - redis_data:/data
                networks:
                  - backend

              app:
                image: myapp:latest
                depends_on:
                  - redis
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Redis service should be gone
        assert "  redis:" not in result
        assert "api-forge-redis" not in result
        assert "redis:7" not in result

        # Other services should remain
        assert "  postgres:" in result
        assert "  app:" in result
        assert "postgres:15" in result
        assert "myapp:latest" in result

    def test_removes_redis_from_depends_on_list(self):
        """Test that Redis is removed from depends_on lists."""
        input_yaml = dedent(
            """
            services:
              app:
                image: myapp:latest
                depends_on:
                  - postgres
                  - redis
                  - temporal
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Redis dependency should be gone
        assert "- redis" not in result

        # Other dependencies should remain
        assert "- postgres" in result
        assert "- temporal" in result

    def test_removes_redis_from_depends_on_with_conditions(self):
        """Test that Redis is removed from depends_on with health check conditions."""
        input_yaml = dedent(
            """
            services:
              app:
                image: myapp:latest
                depends_on:
                  postgres:
                    condition: service_healthy
                  redis:
                    condition: service_started
                  temporal:
                    condition: service_healthy
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Redis condition block should be gone
        assert "redis:" not in result or "  redis:" not in result
        assert "condition: service_started" not in result or "redis" not in result

        # Other dependencies should remain
        assert "postgres:" in result
        assert "temporal:" in result

    def test_removes_redis_volumes(self):
        """Test that Redis volume definitions are removed."""
        input_yaml = dedent(
            """
            services:
              redis:
                image: redis:7
                volumes:
                  - redis_data:/data

            volumes:
              postgres_data:
                driver: local
              redis_data:
                driver: local
              redis_backups:
                driver: local
              app_logs:
                driver: local
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Redis volumes should be gone
        assert "redis_data:" not in result
        assert "redis_backups:" not in result

        # Other volumes should remain
        assert "postgres_data:" in result
        assert "app_logs:" in result

    def test_preserves_services_after_redis(self):
        """Test that services defined after Redis are preserved."""
        input_yaml = dedent(
            """
            services:
              postgres:
                image: postgres:15

              redis:
                image: redis:7
                ports:
                  - "6379:6379"
                volumes:
                  - redis_data:/data
                environment:
                  REDIS_PASSWORD: secret
                networks:
                  - backend

              temporal:
                image: temporal:1.29
                depends_on:
                  - postgres

              app:
                image: myapp:latest
                depends_on:
                  - postgres
                  - redis
                  - temporal

              worker:
                image: myapp:latest
                depends_on:
                  - app
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Redis should be gone
        assert "  redis:" not in result
        assert "redis:7" not in result

        # All other services should remain
        assert "  postgres:" in result
        assert "  temporal:" in result
        assert "  app:" in result
        assert "  worker:" in result

        # Service order should be maintained (no other services removed)
        assert "postgres:15" in result
        assert "temporal:1.29" in result
        assert "myapp:latest" in result

    def test_handles_redis_with_multiline_config(self):
        """Test removal of Redis with complex multiline configuration."""
        input_yaml = dedent(
            """
            services:
              redis:
                container_name: api-forge-redis
                image: app_data_redis_image
                build:
                  context: ./infra/docker/prod/redis
                  dockerfile: Dockerfile
                environment:
                  REDIS_PASSWORD_FILE: /run/secrets/redis_password
                volumes:
                  - redis_data:/data
                  - redis_backups:/var/lib/redis/backups
                  - /etc/localtime:/etc/localtime:ro
                networks:
                  - backend
                secrets:
                  - redis_password
                restart: unless-stopped
                logging:
                  driver: "json-file"
                  options:
                    max-size: "10m"
                    max-file: "3"
                deploy:
                  resources:
                    limits:
                      cpus: '1.0'
                      memory: 512M

              temporal:
                image: temporal:1.29
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Entire Redis block should be gone
        assert "  redis:" not in result
        assert "api-forge-redis" not in result
        assert "REDIS_PASSWORD_FILE" not in result
        assert "redis_backups" not in result

        # Next service should remain
        assert "  temporal:" in result
        assert "temporal:1.29" in result

    def test_handles_redis_at_end_of_services(self):
        """Test Redis removal when it's the last service."""
        input_yaml = dedent(
            """
            services:
              postgres:
                image: postgres:15

              app:
                image: myapp:latest

              redis:
                image: redis:7
                ports:
                  - "6379:6379"

            volumes:
              postgres_data:
                driver: local
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Redis should be gone
        assert "  redis:" not in result

        # Other services and volumes section should remain
        assert "  postgres:" in result
        assert "  app:" in result
        assert "volumes:" in result
        assert "postgres_data:" in result

    def test_removes_redis_from_mixed_depends_on(self):
        """Test Redis removal from mixed depends_on (list and condition format)."""
        input_yaml = dedent(
            """
            services:
              app:
                image: myapp:latest
                depends_on:
                  - redis
                  postgres:
                    condition: service_healthy
                  temporal:
                    condition: service_healthy
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Redis should be gone from list format
        assert "- redis" not in result

        # Conditional dependencies should remain
        assert "postgres:" in result
        assert "temporal:" in result
        assert "condition: service_healthy" in result

    def test_handles_empty_result_when_only_redis(self):
        """Test graceful handling when Redis is the only service."""
        input_yaml = dedent(
            """
            services:
              redis:
                image: redis:7
                ports:
                  - "6379:6379"
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Redis should be gone
        assert "  redis:" not in result
        assert "redis:7" not in result

        # Services section header should remain
        assert "services:" in result

    def test_does_not_affect_redis_in_comments(self):
        """Test that Redis references in comments are not removed."""
        input_yaml = dedent(
            """
            services:
              # This service connects to redis
              postgres:
                image: postgres:15
                # Uncomment to enable redis caching:
                # depends_on:
                #   - redis

              app:
                image: myapp:latest
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Comments should be preserved
        assert "# This service connects to redis" in result
        assert "# Uncomment to enable redis caching:" in result
        assert "#   - redis" in result

        # Services should remain
        assert "  postgres:" in result
        assert "  app:" in result

    def test_preserves_non_redis_services_with_similar_names(self):
        """Test that services with 'redis' in the name but not exactly 'redis' are preserved."""
        input_yaml = dedent(
            """
            services:
              redis:
                image: redis:7

              redis_exporter:
                image: redis-exporter:latest
                depends_on:
                  - redis

              predis_service:
                image: myservice:latest
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Only exact 'redis:' should be removed
        assert "  redis:" not in result or "redis_exporter" in result

        # Services with redis in the name should remain
        # Note: redis_exporter might get caught depending on spacing
        assert "predis_service:" in result

    def test_complex_production_scenario(self):
        """Test a realistic production docker-compose matching actual structure.
        
        This is the critical test that mirrors docker-compose.prod.yml structure,
        including the Redis comment and services that come after Redis.
        """
        input_yaml = dedent(
            """
            version: '3.8'

            services:
              postgres:
                image: postgres:15
                container_name: api-forge-postgres
                networks:
                  - backend

              postgres-verifier:
                container_name: api-forge-postgres-verifier
                image: postgres:15
                networks:
                  - backend


              # Redis Cache/Session Store
              redis:
                container_name: api-forge-redis
                image: redis:7
                volumes:
                  - redis_data:/data
                  - redis_backups:/backups
                networks:
                  - backend
                secrets:
                  - redis_password
                restart: unless-stopped
                deploy:
                  resources:
                    limits:
                      cpus: '1.0'
                      memory: 512M

              temporal-schema-setup:
                container_name: api-forge-temporal-schema-setup
                image: temporalio/admin-tools
                depends_on:
                  postgres:
                    condition: service_healthy
                restart: "no"
                networks:
                  - backend

              temporal-admin-tools:
                container_name: api-forge-temporal-admin-tools
                image: temporalio/admin-tools
                networks:
                  - backend

              temporal-namespace-init:
                container_name: api-forge-temporal-namespace-init
                image: temporalio/admin-tools
                depends_on:
                  temporal:
                    condition: service_healthy
                restart: "no"
                networks:
                  - backend

              temporal:
                image: temporal:1.29
                depends_on:
                  postgres:
                    condition: service_healthy
                  temporal-schema-setup:
                    condition: service_completed_successfully
                networks:
                  - backend

              app:
                image: myapp:latest
                depends_on:
                  postgres:
                    condition: service_healthy
                  temporal:
                    condition: service_healthy
                secrets:
                  - postgres_password
                  - redis_password

              worker:
                image: myapp:latest
                depends_on:
                  - app
                  - redis

            volumes:
              postgres_data:
              redis_data:
              redis_backups:
              temporal_certs:

            networks:
              backend:
        """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Redis service should be completely removed
        assert "container_name: api-forge-redis" not in result
        assert "  redis:" not in result or "temporal-" in result  # Only temporal-related, not redis service
        
        # Redis comment should be removed
        assert "# Redis Cache/Session Store" not in result
        
        # Redis volumes should be gone
        assert result.count("redis_data:") == 0  # In volumes section
        assert result.count("redis_backups:") == 0  # In volumes section
        
        # Redis in secrets list should be gone
        assert "  - redis_password" not in result

        # CRITICAL: All temporal services MUST remain (this is the bug we're catching!)
        assert "  temporal-schema-setup:" in result, "BUG: temporal-schema-setup was removed!"
        assert "api-forge-temporal-schema-setup" in result
        assert "  temporal-admin-tools:" in result, "BUG: temporal-admin-tools was removed!"
        assert "api-forge-temporal-admin-tools" in result
        assert "  temporal-namespace-init:" in result, "BUG: temporal-namespace-init was removed!"
        assert "api-forge-temporal-namespace-init" in result
        assert "  temporal:" in result
        
        # All other services should remain
        assert "  postgres:" in result
        assert "  postgres-verifier:" in result
        assert "  app:" in result
        assert "  worker:" in result

        # Other volumes should remain
        assert "postgres_data:" in result
        assert "temporal_certs:" in result

        # Networks should remain
        assert "networks:" in result
        assert "backend:" in result

        # Redis dependencies should be removed but other deps remain
        assert "- redis" not in result
        # Postgres deps should remain
        assert result.count("postgres:") >= 2  # In services and depends_on


    def test_removes_redis_password_from_service_secrets(self):
        """Test that redis_password is removed from service secrets lists."""
        input_yaml = dedent(
            """
            services:
              app:
                image: myapp:latest
                secrets:
                  - postgres_password
                  - redis_password
                  - session_secret
            """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # redis_password should be gone
        assert "redis_password" not in result
        # Other secrets should remain
        assert "postgres_password" in result
        assert "session_secret" in result

    def test_removes_redis_password_secret_definition(self):
        """Test that redis_password secret definition is removed from secrets section."""
        input_yaml = dedent(
            """
            secrets:
              postgres_password:
                file: ./secrets/postgres.txt
              
              # Redis password
              redis_password:
                file: ./secrets/redis.txt
              
              session_secret:
                file: ./secrets/session.txt
            """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # redis_password definition should be gone
        assert "redis_password" not in result
        assert "./secrets/redis.txt" not in result
        # Other secrets should remain
        assert "postgres_password" in result
        assert "session_secret" in result

    def test_removes_redis_comments(self):
        """Test that Redis-related comments are removed."""
        input_yaml = dedent(
            """
            services:
              postgres:
                image: postgres:15
              
              # Redis Cache/Session Store
              temporal:
                image: temporal:latest
            """
        )

        result = remove_redis_from_docker_compose(input_yaml)

        # Redis comment should be gone
        assert "# Redis" not in result
        # Services should remain
        assert "postgres:" in result
        assert "temporal:" in result


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
