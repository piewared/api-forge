#!/usr/bin/env python3
"""
Post-generation setup script for Copier template.

This script runs after the template has been copied to customize files
that can't contain Jinja2 templates (like pyproject.toml).
"""

import re
import sys
from pathlib import Path


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
        'description = "A FastAPI service built with hexagonal architecture"':
            f'description = "{answers["project_description"]}"',
        'requires-python = ">=3.13"': f'requires-python = ">={answers["python_version"]}"',
        'api-forge-init-db = "src.app.runtime.init_db:init_db"':
            f'{answers["project_slug"]}-init-db = "{answers["package_name"]}.app.runtime.init_db:init_db"',
        'api-forge-cli = "src.cli:app"':
            f'api-forge-cli = "{answers["package_name"]}.cli.__main__:app"',
        'packages = ["src"]':
            f'packages = ["{answers["package_name"]}"]',
        'target-version = "py313"':
            f'target-version = "py{answers["python_version"].replace(".", "")}"',
        'python_version = "3.13"':
            f'python_version = "{answers["python_version"]}"',
    }

    for old, new in replacements.items():
        content = content.replace(old, new)

    # Handle optional fields
    if answers["author_name"] and answers["author_email"]:
        # Replace the placeholder authors with actual values
        content = re.sub(
            r'authors = \[\s*\{name = "Your Name", email = "your\.email@example\.com"\}\s*\]',
            f'authors = [\n    {{name = "{answers["author_name"]}", email = "{answers["author_email"]}"}}\n]',
            content
        )

    if answers["license"] != "None":
        # Add license after requires-python
        license_block = f'license = {{text = "{answers["license"]}"}}\n'
        content = re.sub(
            r'(requires-python = "[^"]*"\n)',
            r'\1' + license_block,
            content
        )

    # Handle conditional dependencies
    if not answers["use_redis"]:
        # Remove Redis-related dependencies
        content = re.sub(
            r'\s+"fastapi-limiter>=[\d.]+",\n',
            '',
            content
        )
        content = re.sub(
            r'\s+"aioredis>=[\d.]+",\n',
            '',
            content
        )

    with open(pyproject_path, 'w') as f:
        f.write(content)

    print("✅ pyproject.toml updated")


def fix_imports_in_files(project_dir: Path, package_name: str):
    """Fix all hardcoded 'src.' imports to use the actual package name."""
    package_dir = project_dir / package_name

    if not package_dir.exists():
        print(f"⚠️  Package directory {package_name}/ not found")
        return

    python_files = list(package_dir.rglob("*.py"))
    fixed_count = 0

    for py_file in python_files:
        try:
            content = py_file.read_text()
            original_content = content

            # Replace 'from src.' with 'from {package_name}.'
            content = re.sub(r'\bfrom src\.', f'from {package_name}.', content)
            # Replace 'import src.' with 'import {package_name}.'
            content = re.sub(r'\bimport src\.', f'import {package_name}.', content)

            if content != original_content:
                py_file.write_text(content)
                fixed_count += 1
        except Exception as e:
            print(f"⚠️  Error processing {py_file}: {e}")

    if fixed_count > 0:
        print(f"✅ Fixed imports in {fixed_count} files")


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


def fix_src_main_imports(project_dir: Path, package_name: str):
    """Fix imports in src_main.py to use the actual package name."""
    src_main_file = project_dir / "src_main.py"
    
    if not src_main_file.exists():
        return
    
    try:
        content = src_main_file.read_text()
        original_content = content
        
        # Replace 'from src.' with 'from {package_name}.'
        content = re.sub(r'\bfrom src\.', f'from {package_name}.', content)
        # Replace 'import src.' with 'import {package_name}.'
        content = re.sub(r'\bimport src\.', f'import {package_name}.', content)
        
        if content != original_content:
            src_main_file.write_text(content)
            print(f"✅ Fixed imports in src_main.py")
    except Exception as e:
        print(f"⚠️  Error processing src_main.py: {e}")


def fix_dockerfile(project_dir: Path, package_name: str):
    """Fix Dockerfile to use the actual package name instead of 'src'."""
    try:
        dockerfile = project_dir / "Dockerfile"
        if not dockerfile.exists():
            return
        
        content = dockerfile.read_text()
        original_content = content
        
        # Replace 'COPY src/ src/' with 'COPY {package_name}/ {package_name}/'
        content = re.sub(
            r'COPY\s+(--chown=\S+\s+)?src/\s+src/',
            rf'COPY \1{package_name}/ {package_name}/',
            content
        )
        
        if content != original_content:
            dockerfile.write_text(content)
            print(f"✅ Fixed Dockerfile to use {package_name}/ instead of src/")
    except Exception as e:
        print(f"⚠️  Error processing Dockerfile: {e}")


def fix_worker_deployment(project_dir: Path, package_name: str):
    """Fix worker deployment to use the actual package name instead of 'src'."""
    try:
        worker_yaml = project_dir / "k8s" / "base" / "deployments" / "worker.yaml"
        if not worker_yaml.exists():
            return
        
        content = worker_yaml.read_text()
        original_content = content
        
        # Replace 'src.worker.main' with '{package_name}.worker.main'
        content = re.sub(
            r'"src\.worker\.main"',
            rf'"{package_name}.worker.main"',
            content
        )
        
        # Replace '/app/src/worker/health_check.py' with '/app/{package_name}/worker/health_check.py'
        content = re.sub(
            r'/app/src/worker/',
            rf'/app/{package_name}/worker/',
            content
        )
        
        if content != original_content:
            worker_yaml.write_text(content)
            print(f"✅ Fixed worker deployment to use {package_name}.worker paths")
    except Exception as e:
        print(f"⚠️  Error processing worker deployment: {e}")


def fix_worker_registry(project_dir: Path, package_name: str):
    """Fix worker registry.py to use the actual package name instead of 'src'."""
    try:
        registry_file = project_dir / package_name / "app" / "worker" / "registry.py"
        if not registry_file.exists():
            return
        
        content = registry_file.read_text()
        original_content = content
        
        # Replace hardcoded "src.app.worker.activities" and "src.app.worker.workflows"
        content = re.sub(
            r'"src\.app\.worker\.(activities|workflows)"',
            rf'"{package_name}.app.worker.\1"',
            content
        )
        
        if content != original_content:
            registry_file.write_text(content)
            print(f"✅ Fixed worker registry to use {package_name}.app.worker paths")
    except Exception as e:
        print(f"⚠️  Error processing worker registry: {e}")


def should_copy_file(file_path: Path, base_dir: Path, gitignore_patterns: list) -> bool:
    """Check if a file should be copied based on gitignore patterns."""
    import fnmatch

    relative_path = file_path.relative_to(base_dir)
    path_str = str(relative_path)

    # Check each pattern
    is_ignored = False
    is_negated = False

    for pattern in gitignore_patterns:
        if not pattern or pattern.startswith('#'):
            continue

        # Handle negation patterns (e.g., !.gitignore)
        if pattern.startswith('!'):
            negation_pattern = pattern[1:]
            if fnmatch.fnmatch(path_str, negation_pattern) or fnmatch.fnmatch(file_path.name, negation_pattern):
                is_negated = True
                continue

        # Handle directory patterns (e.g., keys/)
        if pattern.endswith('/'):
            dir_pattern = pattern.rstrip('/')
            if path_str.startswith(dir_pattern + '/') or path_str == dir_pattern:
                is_ignored = True
                continue

        # Handle wildcard patterns
        if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(file_path.name, pattern):
            is_ignored = True

    # If file is explicitly negated (e.g., !.gitignore), always copy it
    if is_negated:
        return True

    # Otherwise, copy only if not ignored
    return not is_ignored


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
            if line and not line.startswith('#') and ': ' in line:
                key, value = line.split(': ', 1)
                # Remove quotes if present
                value = value.strip().strip('"').strip("'")
                # Convert boolean strings
                if value.lower() in ('true', 'yes'):
                    value = True
                elif value.lower() in ('false', 'no'):
                    value = False
                answers[key] = value

    package_name = answers.get('package_name', 'src')

    print(f"📝 Package name: {package_name}")
    print(f"📝 Project slug: {answers.get('project_slug', 'unknown')}")

    # Run setup steps
    try:
        # 1. Ensure infra/secrets directory structure
        copy_infra_secrets(project_dir)

        # 2. Rename package directory
        rename_package_directory(project_dir, package_name)

        # 3. Fix all hardcoded 'src.' imports in package files
        fix_imports_in_files(project_dir, package_name)

        # 4. Fix imports in src_main.py
        fix_src_main_imports(project_dir, package_name)

        # 5. Fix Dockerfile to use package name
        fix_dockerfile(project_dir, package_name)

        # 6. Fix worker deployment to use package name
        fix_worker_deployment(project_dir, package_name)

        # 7. Fix worker registry autodiscovery paths
        fix_worker_registry(project_dir, package_name)

        # 8. Update pyproject.toml
        update_pyproject_toml(project_dir, answers)

        print("\n✅ Post-generation setup complete!")
        print(f"\n📁 Your project is ready at: {project_dir}")
        print("\n🚀 Next steps:")
        print(f"   1. cd {project_dir}")
        print("   2. cp .env.example .env and configure your environment")
        print("   3. Install dependencies: uv sync")
        print("   4. Generate secrets (required for production/k8s deployments):")
        print("      uv run api-forge-cli secrets generate")
        print("   5. Deploy:")
        print("      • Development (Docker Compose):   uv run api-forge-cli deploy up dev")
        print("      • Production (Docker Compose):    uv run api-forge-cli deploy up prod")
        print("      • Production (Kubernetes):        uv run api-forge-cli deploy up k8s")
        print("\n💡 View all CLI commands: uv run api-forge-cli --help")

    except Exception as e:
        print(f"\n❌ Setup error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
