#!/usr/bin/env sh
set -eu

# Universal Docker Secrets Entrypoint Script
# Handles secret file management for any containerized service
# 
# Environment Variables:
#   CONTAINER_USER_UID - User ID to run the service as (default: 1001)
#   CONTAINER_USER_GID - Group ID to run the service as (default: 1001)
#   SECRETS_SOURCE_DIR - Directory containing mounted host secrets (default: /run/secrets)
#   KEYS_TARGET_DIR - Directory to copy keys/passwords to (default: /app/keys)
#   CERTS_TARGET_DIR - Directory to copy certificates to (default: /app/certs)
#   CREATE_ENV_VARS - Set to "true" to create environment variables from secrets (default: true)
#   SKIP_USER_SWITCH - Set to "true" to skip dropping privileges (default: false)

# Set defaults
CONTAINER_USER_UID=${CONTAINER_USER_UID:-1001}
CONTAINER_USER_GID=${CONTAINER_USER_GID:-1001}
SECRETS_SOURCE_DIR=${SECRETS_SOURCE_DIR:-/run/secrets}
KEYS_TARGET_DIR=${KEYS_TARGET_DIR:-/app/keys}
CERTS_TARGET_DIR=${CERTS_TARGET_DIR:-/app/certs}
CREATE_ENV_VARS=${CREATE_ENV_VARS:-true}
SKIP_USER_SWITCH=${SKIP_USER_SWITCH:-false}
TLS_COPY_SECRETS=${TLS_COPY_SECRETS:-true}

# If skipping user switch, use current user for file ownership
if [ "$SKIP_USER_SWITCH" = "true" ]; then
    CONTAINER_USER_UID=$(id -u)
    CONTAINER_USER_GID=$(id -g)
fi

echo "Starting universal secrets entrypoint script..."
echo "Container UID:GID = ${CONTAINER_USER_UID}:${CONTAINER_USER_GID}"
echo "Source directory = ${SECRETS_SOURCE_DIR}"
echo "Target directories = ${KEYS_TARGET_DIR} (keys), ${CERTS_TARGET_DIR} (certs)"
[ "$TLS_COPY_SECRETS" = "true" ] && echo "TLS destination = ${CERTS_TARGET_DIR}"

# Create secure tmpfs directory for secrets with proper ownership
echo "Setting up secure secrets directory..."
install -d -m 0700 -o "$CONTAINER_USER_UID" -g "$CONTAINER_USER_GID" "$KEYS_TARGET_DIR"
install -d -m 0700 -o "$CONTAINER_USER_UID" -g "$CONTAINER_USER_GID" "$CERTS_TARGET_DIR"


have_secrets_dir=false
if [ -d "$SECRETS_SOURCE_DIR" ] && [ "$(ls -A "$SECRETS_SOURCE_DIR" 2>/dev/null)" ]; then
    have_secrets_dir=true
fi



# Copy all mounted host secrets to tmpfs with proper ownership and permissions
if $have_secrets_dir; then
    echo "Copying secrets with proper permissions..."

    for secret_file in "$SECRETS_SOURCE_DIR"/*; do
        [ -f "$secret_file" ] || continue
        secret_name=$(basename "$secret_file")

        # Skip README and documentation files
        case "$secret_name" in
            README* | readme* | *.md | *.txt.example | *.sample)
                echo "Skipping documentation file: $secret_name"
                continue
                ;;
        esac

        # Remove common extensions to match config expectations
        target_name="${secret_name%.txt}"
        target_name="${target_name%.secret}"
        # NOTE: We keep ".key" removal for env-var naming, but we'll separately copy TLS files (see below).
        target_name="${target_name%.key}"

        echo "Installing secret: $secret_name -> $target_name"
        install -m 0400 -o "$CONTAINER_USER_UID" -g "$CONTAINER_USER_GID" "$secret_file" "$KEYS_TARGET_DIR/$target_name"

        # Create environment variable if requested
        if [ "$CREATE_ENV_VARS" = "true" ]; then
            # Convert filename to uppercase environment variable name
            env_name=$(echo "$target_name" | tr '[:lower:]' '[:upper:]' | tr '-' '_' | sed 's/[^A-Z0-9_]/_/g')
            case "$env_name" in
                [0-9]*) env_name="_$env_name" ;;
            esac
            if [ -n "$env_name" ] && [ "$env_name" != "_" ]; then
                # Single-line vs multi-line handling
                line_count=$(awk 'END{print NR}' "$secret_file")
                if [ "$line_count" -le 1 ]; then
                    secret_content=$(cat "$secret_file")
                    export "$env_name"="$secret_content"
                    echo "Created env: $env_name (single-line)"
                else
                    # You can optionally export a *_FILE var here if desired
                    # export "${env_name}_FILE"="$KEYS_TARGET_DIR/$target_name"
                    echo "Multi-line secret detected for $env_name (no direct env export)"
                fi
            else
                echo "Skipping invalid environment variable name for: $target_name"
            fi
        fi
    done
else
    echo "No secrets directory found or directory is empty: $SECRETS_SOURCE_DIR"
fi

# === TLS: copy *.crt / *.key with strict perms & proper ownership ============
if [ "$TLS_COPY_SECRETS" = "true" ] && $have_secrets_dir; then
    echo "Processing TLS materials (*.crt, *.key) -> $CERTS_TARGET_DIR"
    install -d -m 0700 -o "$CONTAINER_USER_UID" -g "$CONTAINER_USER_GID" "$CERTS_TARGET_DIR"

    copied_any=false
    for f in "$SECRETS_SOURCE_DIR"/*; do
        [ -f "$f" ] || continue
        case "$f" in
            *.crt|*.key)
                base=$(basename "$f")
                cp "$f" "$CERTS_TARGET_DIR/$base"
                chown "$CONTAINER_USER_UID":"$CONTAINER_USER_GID" "$CERTS_TARGET_DIR/$base"
                # perms: 0600 for keys, 0644 for certs
                case "$base" in
                    *.key) chmod 600 "$CERTS_TARGET_DIR/$base" ;;
                    *.crt) chmod 644 "$CERTS_TARGET_DIR/$base" ;;
                esac
                echo "Installed TLS file: $base in $CERTS_TARGET_DIR"
                copied_any=true
                ;;
        esac
    done

    if [ "$copied_any" = false ]; then
        echo "No *.crt or *.key files found in $SECRETS_SOURCE_DIR"
    fi
fi


echo "Secrets setup complete."

# Fix ownership of writable app directories.
# When a volume is mounted (e.g. on Fly.io), the host mounts it as root
# (uid:0 gid:0) which overwrites the Dockerfile-time chown. Re-apply
# ownership here while we still run as root, before dropping privileges.
for _dir in /app/logs /app/data /app/keys /app/certs; do
    if [ -d "$_dir" ]; then
        chown -R "${CONTAINER_USER_UID}:${CONTAINER_USER_GID}" "$_dir"
    fi
done


# Drop privileges and start the application (unless explicitly skipped)
if [ "$SKIP_USER_SWITCH" = "false" ]; then
    echo "Starting application as user ${CONTAINER_USER_UID}:${CONTAINER_USER_GID}..."
    # No need to source any file; env already set and inherited
    if command -v gosu >/dev/null 2>&1; then
        exec gosu "$CONTAINER_USER_UID:$CONTAINER_USER_GID" "$@"
    elif command -v su-exec >/dev/null 2>&1; then
        exec su-exec "$CONTAINER_USER_UID:$CONTAINER_USER_GID" "$@"
    else
        echo "Neither gosu nor su-exec is installed"; exit 127
    fi
else
    echo "Skipping user switch, starting application as current user: $(id -u):$(id -g)"
    exec "$@"
fi