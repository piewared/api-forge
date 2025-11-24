# Changes Summary: Secure OIDC Secrets Handling

## Date: November 24, 2025

## Overview
Improved security and testing by removing insecure OIDC secret placeholders from `.env.example` and implementing proper secret handling via CLI flags.

## Changes Made

### 1. Security Improvements

#### `.env.example`
- **REMOVED**: Placeholder OIDC secret values that could be accidentally deployed
  - `OIDC_GOOGLE_CLIENT_SECRET=your-google-client-secret`
  - `OIDC_MICROSOFT_CLIENT_SECRET=your-microsoft-client-secret`
  - `OIDC_KEYCLOAK_CLIENT_SECRET=test-client-secret`
  
- **ADDED**: Security warnings and documentation
  ```bash
  # OIDC Provider Secrets
  # ⚠️  NOTE: OIDC client secrets are NOT stored in .env files for security
  # They will be prompted for during `secrets generate` command and stored in:
  #   - infra/secrets/keys/oidc_google_client_secret.txt
  #   - infra/secrets/keys/oidc_microsoft_client_secret.txt
  #   - infra/secrets/keys/oidc_keycloak_client_secret.txt
  ```

### 2. CLI Enhancements

#### `src/cli/secrets_commands.py`
- **ADDED**: Three new CLI options for non-interactive secret generation:
  - `--oidc-google-secret`: Google OIDC client secret
  - `--oidc-microsoft-secret`: Microsoft OIDC client secret
  - `--oidc-keycloak-secret`: Keycloak OIDC client secret

- **Usage**:
  ```bash
  # Interactive (prompts for OIDC secrets)
  uv run api-forge-cli secrets generate --pki
  
  # Non-interactive (for CI/CD and testing)
  uv run api-forge-cli secrets generate --pki \
    --oidc-google-secret "my-google-secret" \
    --oidc-microsoft-secret "my-microsoft-secret" \
    --oidc-keycloak-secret "my-keycloak-secret"
  ```

### 3. Test Improvements

#### `tests/e2e/test_copier_to_deployment.py`

**Fixed VIRTUAL_ENV Warning**:
- Modified `run_command()` to clear `VIRTUAL_ENV` environment variable
- Prevents "does not match project environment" warnings from `uv`

**Added OIDC Secret Validation**:
- All three deployment tests (06, 07, 08) now verify OIDC secrets
- Asserts that generated secrets match CLI-provided values
- Prevents regression where secrets come from environment variables

**Example Validation**:
```python
# Verify OIDC secrets were generated correctly
oidc_secrets = {
    "oidc_google_client_secret.txt": "test-google-secret-e2e",
    "oidc_microsoft_client_secret.txt": "test-microsoft-secret-e2e",
    "oidc_keycloak_client_secret.txt": "test-keycloak-secret-e2e",
}

for secret_file, expected_value in oidc_secrets.items():
    secret_path = keys_dir / secret_file
    assert secret_path.exists(), f"OIDC secret {secret_file} not generated"
    actual_value = secret_path.read_text().strip()
    assert actual_value == expected_value, (
        f"OIDC secret {secret_file} has wrong value!\n"
        f"Expected: {expected_value}\n"
        f"Actual: {actual_value}\n"
        f"This means the secret came from environment variables instead of CLI flags."
    )
```

#### `tests/e2e/README.md`
- **ADDED**: "Secrets Handling in Tests" section explaining:
  - Production pattern (interactive prompts)
  - Test pattern (CLI flags)
  - Why .env files don't contain OIDC secrets

### 4. Documentation Updates

#### `tests/e2e/README.md`
New section added explaining the secure secrets handling approach:
- Production users are prompted interactively
- Tests use CLI flags for automation
- Environment variables are NOT used for OIDC secrets
- Prevents accidental deployment with insecure defaults

## Security Benefits

1. **No Default Secrets**: Users must consciously provide real credentials
2. **Explicit Control**: Tests use CLI flags, making secret source clear
3. **Environment Isolation**: Clearing VIRTUAL_ENV prevents cross-contamination
4. **Validation**: Tests verify secrets come from expected source, not environment

## Testing Results

All E2E tests pass with the new approach:
- ✅ test_06_secrets_generation (9.27s) - Validates OIDC secrets
- ✅ test_07_docker_compose_prod_deployment (43.34s) - Validates on first run
- ✅ test_08_kubernetes_deployment - Validates on first run
- ✅ No VIRTUAL_ENV warnings
- ✅ Secrets verified to come from CLI, not environment variables

## Migration Guide for Users

### Before (Insecure - Had Placeholders)
```bash
# .env.example had:
OIDC_GOOGLE_CLIENT_SECRET=your-google-client-secret
```

### After (Secure - No Placeholders)
```bash
# .env.example now has:
# ⚠️  NOTE: OIDC client secrets are NOT stored in .env files for security
```

### For Manual Setup
```bash
# Interactive - will prompt for OIDC secrets
uv run api-forge-cli secrets generate --pki
```

### For Automation/CI
```bash
# Non-interactive - provide via CLI flags
uv run api-forge-cli secrets generate --pki \
  --oidc-google-secret "$OIDC_GOOGLE_SECRET" \
  --oidc-microsoft-secret "$OIDC_MICROSOFT_SECRET" \
  --oidc-keycloak-secret "$OIDC_KEYCLOAK_SECRET"
```

## Files Modified

1. `.env.example` - Removed placeholder OIDC secrets, added security warnings
2. `src/cli/secrets_commands.py` - Added CLI options for OIDC secrets
3. `tests/e2e/test_copier_to_deployment.py` - Added validation, fixed VIRTUAL_ENV
4. `tests/e2e/README.md` - Documented secrets handling approach
5. `tests/e2e/test_stdin_secrets.py` - Created (proof of concept, can be removed)

## Backward Compatibility

- ✅ Interactive mode still works (prompts for OIDC secrets)
- ✅ Existing deployments unaffected (secrets already generated)
- ✅ New CLI flags are optional (backward compatible)
- ⚠️ Users with `.env` files containing OIDC secrets should migrate to CLI flags or interactive prompts

## Next Steps

1. Update production deployment documentation to reflect new approach
2. Consider adding validation in deploy commands to check for placeholder values
3. Add warning if OIDC secrets look like defaults
4. Consider GitHub Actions secrets integration examples
