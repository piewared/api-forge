#!/usr/bin/env python3
"""
Post-generation setup script for Copier template.

This script runs after the template has been copied to customize files
that can't contain Jinja2 templates (like pyproject.toml).
"""

import importlib
import re
import sys
from pathlib import Path

from docker_compose_utils import remove_redis_from_docker_compose


def update_pyproject_toml(project_dir: Path, answers: dict):
    """Update pyproject.toml with values from copier answers."""
    pyproject_path = project_dir / "pyproject.toml"

    if not pyproject_path.exists():
        print(f"⚠️  pyproject.toml not found at {pyproject_path}")
        return

    print("📝 Updating pyproject.toml...")

    with open(pyproject_path) as f:
        content = f.read()

    # Replace placeholders with actual values
    replacements = {
        'name = "api-forge"': f'name = "{answers["project_slug"]}"',
        'version = "0.1.0"': f'version = "{answers["version"]}"',
        'description = "Production-ready API platform with OIDC auth, PostgreSQL, Redis, Temporal workflows, and Kubernetes deployment"': f'description = "{answers["project_description"]}"',
        'requires-python = ">=3.13"': f'requires-python = ">={answers["python_version"]}"',
        'api-forge-init-db = "src.app.runtime.init_db:init_db"': f'init-db = "{answers["package_name"]}.app.runtime.init_db:init_db"',
        'api-forge-cli = "src.cli:app"': f'api-forge-cli = "{answers["package_name"]}.cli:app"',
        'packages = ["src"]': f'packages = ["{answers["package_name"]}"]',
        'target-version = "py313"': f'target-version = "py{answers["python_version"].replace(".", "")}"',
        'python_version = "3.13"': f'python_version = "{answers["python_version"]}"',
    }

    for old, new in replacements.items():
        content = content.replace(old, new)

    # Handle optional fields
    if answers.get("author_name") and answers.get("author_email"):
        # Replace the placeholder authors with actual values
        content = re.sub(
            r'authors = \[\s*\{name = "Your Name", email = "your\.email@example\.com"\}\s*\]',
            f'authors = [\n    {{name = "{answers["author_name"]}", email = "{answers["author_email"]}"}}\n]',
            content,
        )

    if answers.get("license", "MIT") != "None":
        # Add license after requires-python
        license_block = f'license = {{text = "{answers["license"]}"}}\n'
        content = re.sub(
            r'(requires-python = "[^"]*"\n)', r"\1" + license_block, content
        )

    # Handle conditional dependencies - Remove Redis if not wanted
    if not answers.get("use_redis", True):
        print("  ⚙️  Removing Redis dependencies (use_redis=false)...")
        # Remove Redis and fastapi-limiter dependencies
        content = re.sub(r'\s+"redis\[hiredis\]>=[\d.]+",\n', "", content)
        content = re.sub(r'\s+"fastapi-limiter>=[\d.]+",\n', "", content)
        content = re.sub(r'\s+"aioredis>=[\d.]+",\n', "", content)
        print("  ✅ Redis dependencies removed")

    with open(pyproject_path, "w") as f:
        f.write(content)

    print("✅ pyproject.toml updated")


def fix_all_src_references(project_dir: Path, package_name: str):
    """
    Globally replace all 'src.' references with '{package_name}.' across the entire project.

    This is more robust than targeting specific files/patterns because it catches:
    - Python imports (from src.app, import src.cli, etc.)
    - Docker COPY commands (COPY src/ src/)
    - YAML command arrays (["python", "-m", "src.worker.main"])
    - File paths (/app/src/worker/)
    - Module strings ("src.app.worker.activities")
    """
    # File extensions and patterns to process
    patterns = ["*.py", "*.yml", "*.yaml", "Dockerfile", "docker-compose*.yml"]

    files_to_process = []
    for pattern in patterns:
        if pattern == "Dockerfile":
            dockerfile = project_dir / "Dockerfile"
            if dockerfile.exists():
                files_to_process.append(dockerfile)
        elif pattern.startswith("docker-compose"):
            files_to_process.extend(project_dir.glob(pattern))
        else:
            files_to_process.extend(project_dir.rglob(pattern))

    # Also add src_main.py explicitly
    src_main = project_dir / "src_main.py"
    if src_main.exists():
        files_to_process.append(src_main)

    fixed_count = 0

    for file_path in files_to_process:
        try:
            # Skip files in certain directories
            if any(
                skip in file_path.parts
                for skip in [".venv", "__pycache__", ".git", "node_modules", "data"]
            ):
                continue

            content = file_path.read_text()
            original_content = content

            # Replace Python imports: from src. / import src.
            content = re.sub(r"\bfrom src\.", f"from {package_name}.", content)
            content = re.sub(r"\bimport src\.", f"import {package_name}.", content)

            # Replace string literals in quotes: "src.worker.main" -> "{package_name}.worker.main"
            content = re.sub(
                r'"src\.(app|cli|dev|utils|worker)', rf'"{package_name}.\1', content
            )
            content = re.sub(
                r"'src\.(app|cli|dev|utils|worker)", rf"'{package_name}.\1", content
            )

            # Replace file paths: /app/src/ -> /app/{package_name}/
            content = re.sub(r"/app/src/", f"/app/{package_name}/", content)

            # Replace Docker COPY: COPY src/ src/ -> COPY {package_name}/ {package_name}/
            content = re.sub(
                r"COPY(\s+--chown=\S+)?\s+src/\s+src/",
                rf"COPY\1 {package_name}/ {package_name}/",
                content,
            )

            if content != original_content:
                file_path.write_text(content)
                fixed_count += 1
        except Exception as e:
            print(f"⚠️  Error processing {file_path}: {e}")

    if fixed_count > 0:
        print(f"✅ Fixed src references in {fixed_count} files")


def rename_package_directory(project_dir: Path, package_name: str):
    """Rename the template package directory to the actual package name."""
    # The template has a 'src' directory that needs to be renamed to package_name
    src_dir = project_dir / "src"
    package_dir = project_dir / package_name

    if src_dir.exists() and not package_dir.exists():
        print(f"📁 Renaming src/ → {package_name}/")
        src_dir.rename(package_dir)
        print(f"✅ Package directory renamed to {package_name}/")
    elif package_dir.exists():
        print(f"✅ Package directory {package_name}/ already exists")
    else:
        print(f"⚠️  Neither src/ nor {package_name}/ found")


def should_copy_file(file_path: Path, base_dir: Path, gitignore_patterns: list) -> bool:
    """Check if a file should be copied based on gitignore patterns."""
    import fnmatch

    relative_path = file_path.relative_to(base_dir)
    path_str = str(relative_path)

    # Check each pattern
    is_ignored = False
    is_negated = False

    for pattern in gitignore_patterns:
        if not pattern or pattern.startswith("#"):
            continue

        # Handle negation patterns (e.g., !.gitignore)
        if pattern.startswith("!"):
            negation_pattern = pattern[1:]
            if fnmatch.fnmatch(path_str, negation_pattern) or fnmatch.fnmatch(
                file_path.name, negation_pattern
            ):
                is_negated = True
                continue

        # Handle directory patterns (e.g., keys/)
        if pattern.endswith("/"):
            dir_pattern = pattern.rstrip("/")
            if path_str.startswith(dir_pattern + "/") or path_str == dir_pattern:
                is_ignored = True
                continue

        # Handle wildcard patterns
        if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(
            file_path.name, pattern
        ):
            is_ignored = True

    # If file is explicitly negated (e.g., !.gitignore), always copy it
    if is_negated:
        return True

    # Otherwise, copy only if not ignored
    return not is_ignored


def remove_redis_dependencies(project_dir: Path):
    """Remove Redis dependencies from pyproject.toml (comprehensive cleanup)."""
    pyproject_path = project_dir / "pyproject.toml"

    if not pyproject_path.exists():
        print(f"⚠️  pyproject.toml not found at {pyproject_path}")
        return

    print("📝 Removing Redis dependencies from pyproject.toml...")

    with open(pyproject_path) as f:
        content = f.read()

    # Remove all Redis-related dependencies
    redis_patterns = [
        r'\s+"redis\[hiredis\]>=[\d.]+",?\n',
        r'\s+"fastapi-limiter>=[\d.]+",?\n',
        r'\s+"aioredis>=[\d.]+",?\n',
    ]

    for pattern in redis_patterns:
        content = re.sub(pattern, "", content)

    with open(pyproject_path, "w") as f:
        f.write(content)

    print("✅ Redis dependencies removed from pyproject.toml")


def update_config_yaml(project_dir: Path, answers: dict):
    """Update config.yaml to disable Redis if not wanted."""

    if not answers.get("use_redis", True):
        print("📝 Updating config.yaml (disabling Redis)...")

        # Dynamic import based on package name
        package_name = answers.get("package_name", "src")
        config_loader = importlib.import_module(
            f"{package_name}.app.runtime.config.config_loader"
        )

        # Load YAML directly without validation
        config_dict = config_loader.load_config(processed=False)

        # Update the redis.enabled field
        if "config" in config_dict and "redis" in config_dict["config"]:
            config_dict["config"]["redis"]["enabled"] = False

        # Save back to file
        config_loader.save_config(config_dict)
        print("✅ config.yaml updated (Redis disabled)")


def update_env_example(project_dir: Path, answers: dict):
    """Update .env.example to remove Redis variables if not wanted."""
    env_path = project_dir / ".env.example"

    if not env_path.exists():
        print(f"⚠️  .env.example not found at {env_path}")
        return

    if not answers.get("use_redis", True):
        print("📝 Updating .env.example (removing Redis vars)...")

        with open(env_path) as f:
            lines = f.readlines()

        # Remove Redis section and variables
        filtered_lines = []
        skip_redis_section = False

        for line in lines:
            # Check if we're entering Redis section
            if "Redis Settings" in line or "Redis Configuration" in line:
                skip_redis_section = True
                continue

            # Check if we're leaving Redis section (next ### marker)
            if skip_redis_section and line.strip().startswith("###"):
                skip_redis_section = False

            # Skip Redis-related lines
            if skip_redis_section or "REDIS_URL" in line or "REDIS_PASSWORD" in line:
                continue

            filtered_lines.append(line)

        with open(env_path, "w") as f:
            f.writelines(filtered_lines)

        print("✅ .env.example updated (Redis variables removed)")


def update_docker_compose(project_dir: Path, answers: dict):
    """Update docker-compose files to remove Redis service if not wanted."""
    if not answers.get("use_redis", True):
        print("📝 Updating docker-compose files (removing Redis)...")

        for compose_file in ["docker-compose.dev.yml", "docker-compose.prod.yml"]:
            compose_path = project_dir / compose_file

            if not compose_path.exists():
                continue

            with open(compose_path) as f:
                content = f.read()

            # Use the centralized function for Redis removal
            content = remove_redis_from_docker_compose(content)

            with open(compose_path, "w") as f:
                f.write(content)

            print(f"  ✅ {compose_file} updated")


def copy_infra_secrets(project_dir: Path):
    """Copy infra/secrets directory while respecting .gitignore patterns."""

    # Source is the template's infra/secrets directory (parent of project_dir during copier run)
    # But since copier has already copied files, we just need to ensure structure exists
    # The actual files should already be in place from copier

    dest_secrets_dir = project_dir / "infra" / "secrets"

    # Ensure directory structure exists
    dest_secrets_dir.mkdir(parents=True, exist_ok=True)
    (dest_secrets_dir / "keys").mkdir(exist_ok=True)
    (dest_secrets_dir / "certs").mkdir(exist_ok=True)

    # Check if files are already present (copied by copier)
    expected_files = [
        dest_secrets_dir / ".gitignore",
        dest_secrets_dir / "README.md",
        dest_secrets_dir / "generate_secrets.sh",
    ]

    all_present = all(f.exists() for f in expected_files)

    if all_present:
        print("✅ infra/secrets/ structure already in place")
    else:
        print("⚠️  Some expected files missing in infra/secrets/")
        for f in expected_files:
            if not f.exists():
                print(f"    Missing: {f.name}")

    return True


def main():
    """Main setup function."""
    # Get the project directory (where copier copied the template)
    if len(sys.argv) < 2:
        print("❌ Error: Project directory not provided")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()

    if not project_dir.exists():
        print(f"❌ Error: Project directory does not exist: {project_dir}")
        sys.exit(1)

    print("🔧 Running post-generation setup...")
    print(f"📁 Project directory: {project_dir}")

    # Load copier answers
    answers_file = project_dir / ".copier-answers.yml"
    if not answers_file.exists():
        print("❌ Error: .copier-answers.yml not found")
        sys.exit(1)

    # Parse YAML manually (simple parsing, no need for PyYAML)
    answers = {}
    with open(answers_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and ": " in line:
                key, value = line.split(": ", 1)
                # Remove quotes if present
                value = value.strip().strip('"').strip("'")
                # Convert boolean strings
                if value.lower() in ("true", "yes"):
                    value = True
                elif value.lower() in ("false", "no"):
                    value = False
                answers[key] = value

    package_name = answers.get("package_name", "src")

    print(f"📝 Package name: {package_name}")
    print(f"📝 Project slug: {answers.get('project_slug', 'unknown')}")

    # Run setup steps
    try:
        # 1. Ensure infra/secrets directory structure
        copy_infra_secrets(project_dir)

        # 2. Rename package directory
        rename_package_directory(project_dir, package_name)

        # 3. Fix ALL 'src.' references throughout the project
        #    This replaces the old fragile approach of targeting specific files
        #    Now handles: Python imports, Docker commands, YAML configs, file paths, etc.
        fix_all_src_references(project_dir, package_name)

        # 4. Update pyproject.toml
        update_pyproject_toml(project_dir, answers)

        # 5. Handle optional Redis removal
        if not answers.get("use_redis", True):
            print("\n🔧 Removing Redis dependencies (use_redis=false)...")
            remove_redis_dependencies(project_dir)
            update_config_yaml(project_dir, answers)
            update_env_example(project_dir, answers)
            update_docker_compose(project_dir, answers)

        print("\n✅ Post-generation setup complete!")
        print(f"\n📁 Your project is ready at: {project_dir}")
        print("\n🚀 Next steps:")
        print(f"   1. cd {project_dir}")
        print("   2. Deactivate any active virtual environment: deactivate (if needed)")
        print("   3. cp .env.example .env and configure your environment")
        print("   4. Install dependencies: uv sync")
        print("   5. Generate secrets (required for production/k8s deployments):")
        print("      uv run api-forge-cli secrets generate --pki")
        print(
            "      (Use --pki to include TLS certificates for PostgreSQL, Redis, Temporal)"
        )
        print("   6. Deploy:")
        print(
            "      • Development (Docker Compose):   uv run api-forge-cli deploy up dev"
        )
        print(
            "      • Production (Docker Compose):    uv run api-forge-cli deploy up prod"
        )
        print(
            "      • Production (Kubernetes):        uv run api-forge-cli deploy up k8s"
        )
        print("\n💡 View all CLI commands: uv run api-forge-cli --help")

    except Exception as e:
        print(f"\n❌ Setup error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
