#!/usr/bin/env sh
set -eu

# --- Inputs (prefer your PRODUCTION_* names if present) ------------------------
APP_DB="${APP_DB:-${APP_DB:-appdb}}"
APP_USER="${APP_DB_USER:-${APP_DB_USER:-appuser}}"
APP_RO="${APP_DB_RO_USER:-${APP_DB_RO_USER:-appreadonly}}"
APP_OWNER="${APP_DB_OWNER:-${APP_DB_OWNER:-owner}}"
TEMPORAL_DB="${TEMPORAL_DB:-${TEMPORAL_DB:-temporal}}"
TEMPORAL_DB_USER="${TEMPORAL_DB_USER:-${TEMPORAL_DB_USER:-temporaluser}}"
TEMPORAL_DB_OWNER="${TEMPORAL_DB_OWNER:-${TEMPORAL_DB_USER}_owner}"
APP_SCHEMA="${APP_SCHEMA:-app}"

# Comma-separated list of subnets that SHOULD be allowed via hostssl
# e.g. "172.30.50.0/24,10.10.0.0/16"
ALLOWED_SUBNETS="${ALLOWED_SUBNETS:-172.30.50.0/24}"

# Optional: where certs live inside Postgres (match your Postgres config/volume)
# If verifier has this path mounted read-only, we can check permissions.
CERT_DIR="${CERT_DIR:-/etc/postgresql/ssl}"
CERT_FILE="${CERT_FILE:-server.crt}"
KEY_FILE="${KEY_FILE:-server.key}"

# --- psql (connect as app_user; PGPASSWORD is provided from Docker secret) -----
PSQL="psql -U ${APP_USER} -w -At -h postgres -d postgres"
PSQL_APP="psql -U ${APP_USER} -w -At -h postgres -d ${APP_DB}"

ok()  { printf "✅ %s\n" "$*"; }
bad() { printf "❌ %s\n" "$*"; exit 1; }
warn(){ printf "⚠️  %s\n" "$*"; }

echo "== Verifying Postgres (host: postgres) =="
echo "   DB=$APP_DB  OWNER=$APP_OWNER  USER=$APP_USER  RO=$APP_RO  SCHEMA=$APP_SCHEMA"
if [ -n "${TEMPORAL_DB_USER:-}" ]; then
  echo "   Temporal DB=$TEMPORAL_DB  USER=$TEMPORAL_DB_USER  OWNER=$TEMPORAL_DB_OWNER"
else
  echo "   Temporal: disabled"
fi
echo

# --- Core: roles / db / schema / grants ---------------------------------------

# App DB roles exist?
[ "$($PSQL -c "SELECT COUNT(*) FROM pg_roles WHERE rolname='${APP_USER}';")" = "1" ] \
  || bad "Role ${APP_USER} does not exist"
[ "$($PSQL -c "SELECT COUNT(*) FROM pg_roles WHERE rolname='${APP_RO}';")" = "1" ] \
  || bad "Role ${APP_RO} does not exist"
[ "$($PSQL -c "SELECT COUNT(*) FROM pg_roles WHERE rolname='${APP_OWNER}';")" = "1" ] \
  || bad "Role ${APP_OWNER} does not exist"

# LOGIN/NOLOGIN checks
[ "$($PSQL -c "SELECT rolcanlogin FROM pg_roles WHERE rolname='${APP_USER}';")" = "t" ] \
  || bad "Role ${APP_USER} missing LOGIN"
[ "$($PSQL -c "SELECT rolcanlogin FROM pg_roles WHERE rolname='${APP_RO}';")" = "t" ] \
  || bad "Role ${APP_RO} missing LOGIN"
[ "$($PSQL -c "SELECT rolcanlogin FROM pg_roles WHERE rolname='${APP_OWNER}';")" = "f" ] \
  || bad "Role ${APP_OWNER} should be NOLOGIN"
ok "App DB role login attributes look correct (${APP_USER}/${APP_RO} LOGIN, ${APP_OWNER} NOLOGIN)"

# Temporal DB roles exist? (only check if Temporal is enabled)
if [ -n "${TEMPORAL_DB_USER:-}" ]; then
  [ "$($PSQL -c "SELECT COUNT(*) FROM pg_roles WHERE rolname='${TEMPORAL_DB_USER}';")" = "1" ] \
    || bad "Role ${TEMPORAL_DB_USER} does not exist"
  [ "$($PSQL -c "SELECT COUNT(*) FROM pg_roles WHERE rolname='${TEMPORAL_DB_OWNER}';")" = "1" ] \
    || bad "Role ${TEMPORAL_DB_OWNER} does not exist"

  # LOGIN/NOLOGIN checks
  [ "$($PSQL -c "SELECT rolcanlogin FROM pg_roles WHERE rolname='${TEMPORAL_DB_USER}';")" = "t" ] \
    || bad "Role ${TEMPORAL_DB_USER} missing LOGIN"
  [ "$($PSQL -c "SELECT rolcanlogin FROM pg_roles WHERE rolname='${TEMPORAL_DB_OWNER}';")" = "f" ] \
    || bad "Role ${TEMPORAL_DB_OWNER} should be NOLOGIN"

  ok "Temporal DB role login attributes look correct (${TEMPORAL_DB_USER} LOGIN, ${TEMPORAL_DB_OWNER} NOLOGIN)"
else
  ok "Temporal disabled, skipping Temporal role checks"
fi

# Database ownership
OWNER="$($PSQL -c "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='${APP_DB}';")"
[ -n "$OWNER" ] || bad "Database ${APP_DB} does not exist"
[ "$OWNER" = "$APP_OWNER" ] || bad "Database ${APP_DB} owner is '${OWNER}' (expected ${APP_OWNER})"
ok "Database ${APP_DB} owner is ${APP_OWNER}"

# Schema ownership
SCHEMA_OWNER="$($PSQL_APP -c "SELECT r.rolname
                               FROM pg_namespace n
                               JOIN pg_roles r ON r.oid = n.nspowner
                               WHERE n.nspname='${APP_SCHEMA}';")"
[ -n "$SCHEMA_OWNER" ] || bad "Schema ${APP_SCHEMA} does not exist in ${APP_DB}"
[ "$SCHEMA_OWNER" = "$APP_OWNER" ] || bad "Schema ${APP_SCHEMA} owner is '${SCHEMA_OWNER}' (expected ${APP_OWNER})"
ok "Schema ${APP_SCHEMA} owner is ${APP_OWNER}"

# Schema privileges (runtime)
[ "$($PSQL_APP -c "SELECT has_schema_privilege('${APP_USER}','${APP_SCHEMA}','USAGE');")" = "t" ] \
  || bad "${APP_USER} missing USAGE on ${APP_SCHEMA}"
[ "$($PSQL_APP -c "SELECT has_schema_privilege('${APP_RO}','${APP_SCHEMA}','USAGE');")" = "t" ] \
  || bad "${APP_RO} missing USAGE on ${APP_SCHEMA}"
ok "Schema privileges (USAGE) look good"

# App user: DML on all tables
MISSING_TBLS_RW="$($PSQL_APP -c "
WITH t AS (
  SELECT quote_ident(n.nspname)||'.'||quote_ident(c.relname) AS fq
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname='${APP_SCHEMA}' AND c.relkind IN ('r','p')
),
missing AS (
  SELECT fq FROM t
  WHERE NOT has_table_privilege('${APP_USER}', fq, 'SELECT')
     OR NOT has_table_privilege('${APP_USER}', fq, 'INSERT')
     OR NOT has_table_privilege('${APP_USER}', fq, 'UPDATE')
     OR NOT has_table_privilege('${APP_USER}', fq, 'DELETE')
)
SELECT COALESCE(string_agg(fq, ', '), '') FROM missing;
")"
[ -z "$MISSING_TBLS_RW" ] && ok "${APP_USER} has DML on all tables in ${APP_SCHEMA}" \
                          || bad "${APP_USER} missing DML on: ${MISSING_TBLS_RW}"

# App user: sequences
MISSING_SEQS_RW="$($PSQL_APP -c "
WITH seqs AS (
  SELECT quote_ident(n.nspname)||'.'||quote_ident(c.relname) AS fq
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname='${APP_SCHEMA}' AND c.relkind='S'
),
missing AS (
  SELECT fq FROM seqs
  WHERE NOT has_sequence_privilege('${APP_USER}', fq, 'USAGE')
     OR NOT has_sequence_privilege('${APP_USER}', fq, 'SELECT')
)
SELECT COALESCE(string_agg(fq, ', '), '') FROM missing;
")"
[ -z "$MISSING_SEQS_RW" ] && ok "${APP_USER} has USAGE,SELECT on all sequences in ${APP_SCHEMA}" \
                          || bad "${APP_USER} missing sequence privileges on: ${MISSING_SEQS_RW}"

# Read-only user: tables
MISSING_TBLS_RO="$($PSQL_APP -c "
WITH t AS (
  SELECT quote_ident(n.nspname)||'.'||quote_ident(c.relname) AS fq
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname='${APP_SCHEMA}' AND c.relkind IN ('r','p')
),
missing AS (
  SELECT fq FROM t
  WHERE NOT has_table_privilege('${APP_RO}', fq, 'SELECT')
)
SELECT COALESCE(string_agg(fq, ', '), '') FROM missing;
")"
[ -z "$MISSING_TBLS_RO" ] && ok "${APP_RO} has SELECT on all tables in ${APP_SCHEMA}" \
                          || bad "${APP_RO} missing SELECT on: ${MISSING_TBLS_RO}"

# Read-only user: sequences (optional but useful for dumps/BI)
MISSING_SEQS_RO="$($PSQL_APP -c "
WITH seqs AS (
  SELECT quote_ident(n.nspname)||'.'||quote_ident(c.relname) AS fq
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname='${APP_SCHEMA}' AND c.relkind='S'
),
missing AS (
  SELECT fq FROM seqs
  WHERE NOT has_sequence_privilege('${APP_RO}', fq, 'SELECT')
)
SELECT COALESCE(string_agg(fq, ', '), '') FROM missing;
")"
[ -z "$MISSING_SEQS_RO" ] && ok "${APP_RO} has SELECT on all sequences in ${APP_SCHEMA}" \
                          || warn "${APP_RO} missing sequence SELECT on: ${MISSING_SEQS_RO}"

# --- OPTIONAL: verify default privileges from owner (best-effort) --------------
# Check if aclexplode function is available (PostgreSQL 9.0+)
HAS_ACLEXPLODE="$($PSQL_APP -c "SELECT COUNT(*) > 0 FROM pg_proc WHERE proname = 'aclexplode';")"
if [ "$HAS_ACLEXPLODE" = "t" ]; then
  MISSING_DEF_TBL="$($PSQL_APP -c "
    WITH d AS (
      SELECT d.defaclobjtype, d.defaclacl
      FROM pg_default_acl d
      JOIN pg_namespace n ON n.oid = d.defaclnamespace
      JOIN pg_roles r ON r.oid = d.defaclrole
      WHERE n.nspname='${APP_SCHEMA}' AND r.rolname='${APP_OWNER}' AND d.defaclobjtype='r'
    ),
    e AS (
      SELECT (aclexplode(defaclacl)).grantee AS grantee, (aclexplode(defaclacl)).privilege_type AS priv
      FROM d
    )
    SELECT COUNT(*) FILTER (WHERE priv='SELECT' AND grantee = (SELECT oid FROM pg_roles WHERE rolname='${APP_USER}')) >= 1
       AND COUNT(*) FILTER (WHERE priv='INSERT' AND grantee = (SELECT oid FROM pg_roles WHERE rolname='${APP_USER}')) >= 1
       AND COUNT(*) FILTER (WHERE priv='UPDATE' AND grantee = (SELECT oid FROM pg_roles WHERE rolname='${APP_USER}')) >= 1
       AND COUNT(*) FILTER (WHERE priv='DELETE' AND grantee = (SELECT oid FROM pg_roles WHERE rolname='${APP_USER}')) >= 1
       AND COUNT(*) FILTER (WHERE priv='SELECT' AND grantee = (SELECT oid FROM pg_roles WHERE rolname='${APP_RO}')) >= 1
    FROM e;
  ")"
  [ "$MISSING_DEF_TBL" = "t" ] && ok "Default privileges (tables) appear correctly set from owner" \
                               || warn "Default privileges (tables) may be missing/incomplete for ${APP_USER}/${APP_RO}"

  MISSING_DEF_SEQ="$($PSQL_APP -c "
    WITH d AS (
      SELECT d.defaclobjtype, d.defaclacl
      FROM pg_default_acl d
      JOIN pg_namespace n ON n.oid = d.defaclnamespace
      JOIN pg_roles r ON r.oid = d.defaclrole
      WHERE n.nspname='${APP_SCHEMA}' AND r.rolname='${APP_OWNER}' AND d.defaclobjtype='S'
    ),
    e AS (
      SELECT (aclexplode(defaclacl)).grantee AS grantee, (aclexplode(defaclacl)).privilege_type AS priv
      FROM d
    )
    SELECT COUNT(*) FILTER (WHERE priv='USAGE' AND grantee = (SELECT oid FROM pg_roles WHERE rolname='${APP_USER}')) >= 1
       AND COUNT(*) FILTER (WHERE priv='SELECT' AND grantee = (SELECT oid FROM pg_roles WHERE rolname='${APP_USER}')) >= 1
       AND COUNT(*) FILTER (WHERE priv='SELECT' AND grantee = (SELECT oid FROM pg_roles WHERE rolname='${APP_RO}')) >= 1
    FROM e;
  ")"
  [ "$MISSING_DEF_SEQ" = "t" ] && ok "Default privileges (sequences) appear correctly set from owner" \
                               || warn "Default privileges (sequences) may be missing/incomplete for ${APP_USER}/${APP_RO}"
else
  warn "Cannot verify default privileges (no aclexplode()); skip or check manually in pg_default_acl"
fi

# --- TLS: server-side settings & connection is actually SSL --------------------
SSL_ON="$($PSQL -c "SHOW ssl;")"
[ "$SSL_ON" = "on" ] || bad "ssl is OFF (SHOW ssl)"
ok "ssl=on"

# Our current session should be SSL (prove it via pg_stat_ssl)
CURR_SSL="$($PSQL -c "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid();")"
[ "$CURR_SSL" = "t" ] && ok "Current connection is using TLS" \
                      || bad "Current connection is NOT using TLS"

# Negative test: non-TLS must fail (sslmode=disable)
if psql "host=postgres dbname=${APP_DB} user=${APP_USER} password=${PGPASSWORD} sslmode=disable" -At -c "select 1" >/dev/null 2>&1; then
  bad "Non-TLS connection (sslmode=disable) unexpectedly succeeded"
else
  ok "Non-TLS connection (sslmode=disable) correctly rejected"
fi

# --- pg_hba: prove TLS-only using parsed rules (pg_hba_file_rules) ------------
# pg_hba_file_rules is superuser-only. We'll try as app_user first; on permission error, retry as superuser if provided.

run_hba_query() {
  q="$1"
  # try as app user first
  if out="$(PGPASSWORD="${PGPASSWORD}" psql -U "${APP_USER}" -w -At -h postgres -d postgres -c "$q" 2>&1)"; then
    printf "%s" "$out"
    return 0
  fi
  # fallback to superuser if permission denied and we have superuser credentials
  if printf "%s" "$out" | grep -qi "permission denied" && [ -n "${PGSU_PASSWORD:-}" ]; then
    if su_out="$(PGPASSWORD="${PGSU_PASSWORD}" psql -U postgres -w -At -h postgres -d postgres -c "$q" 2>&1)"; then
      printf "%s" "$su_out"
      return 0
    else
      printf "%s" "$su_out" >&2
      return 1
    fi
  fi
  printf "%s" "$out" >&2
  return 1
}

# 1) hostnossl rejects for v4/v6
HBA_V4_REJECT="$(run_hba_query "
  SELECT count(*) FROM pg_hba_file_rules
  WHERE type='hostnossl' AND auth_method='reject' AND address='0.0.0.0' AND netmask='0.0.0.0';
")" || bad "pg_hba_file_rules not accessible and no superuser provided"
[ "$HBA_V4_REJECT" -ge 1 ] && ok "pg_hba: hostnossl v4 reject present" \
                           || warn "pg_hba: hostnossl v4 reject not found"

HBA_V6_REJECT="$(run_hba_query "
  SELECT count(*) FROM pg_hba_file_rules
  WHERE type='hostnossl' AND auth_method='reject' AND address='::' AND netmask='::';
")"
[ "$HBA_V6_REJECT" -ge 1 ] && ok "pg_hba: hostnossl v6 reject present" \
                           || warn "pg_hba: hostnossl v6 reject not found"

# Helper function to convert CIDR to address/netmask for pg_hba_file_rules queries
cidr_to_address_netmask() {
  local cidr="$1"
  local ip="${cidr%/*}"
  local prefix="${cidr#*/}"
  
  case "$ip" in
    *:*) # IPv6
      if [ "$prefix" = "0" ]; then
        echo "address='::' AND netmask='::'"
      else
        # For simplicity, just match the network address
        echo "address='$ip'"
      fi
      ;;
    *) # IPv4
      case "$prefix" in
        0)  echo "address='0.0.0.0' AND netmask='0.0.0.0'" ;;
        8)  echo "address='${ip}' AND netmask='255.0.0.0'" ;;
        16) echo "address='${ip}' AND netmask='255.255.0.0'" ;;
        24) echo "address='${ip}' AND netmask='255.255.255.0'" ;;
        32) echo "address='${ip}' AND netmask='255.255.255.255'" ;;
        *)  echo "address='${ip}'" ;; # fallback: just match address
      esac
      ;;
  esac
}

# 2) For each allowed subnet, ensure there is a hostssl allow with scram-sha-256 or md5
OLDIFS="$IFS"
IFS=','; for cidr in $ALLOWED_SUBNETS; do
  cidr="$(echo "$cidr" | tr -d ' ')"
  [ -z "$cidr" ] && continue
  
  # Convert CIDR to address/netmask format
  addr_mask="$(cidr_to_address_netmask "$cidr")"
  
  HAS_ALLOW="$(run_hba_query "
    SELECT count(*) FROM pg_hba_file_rules
    WHERE type='hostssl' AND ${addr_mask} AND auth_method IN ('scram-sha-256','md5');
  ")"
  [ "$HAS_ALLOW" -ge 1 ] && ok "pg_hba: hostssl allow present for ${cidr}" \
                         || bad "pg_hba: missing hostssl allow for ${cidr}"
done
IFS="$OLDIFS"

# 3) Broad non-TLS host rules
HAS_BROAD_HOST="$(run_hba_query "
  SELECT count(*) FROM pg_hba_file_rules
  WHERE type='host' AND 
        ((address='0.0.0.0' AND netmask='0.0.0.0') OR 
         (address='::' AND netmask='::') OR 
         address IS NULL)
    AND auth_method IN ('scram-sha-256','md5');
")"
[ "$HAS_BROAD_HOST" -eq 0 ] && ok "pg_hba: no broad non-TLS 'host' rules" \
                             || warn "pg_hba: found broad non-TLS 'host' rule (tighten to hostssl)"

# --- OPTIONAL: file-level cert checks (only if mounted) ------------------------
if [ -f "${CERT_DIR}/${CERT_FILE}" ] && [ -f "${CERT_DIR}/${KEY_FILE}" ]; then
  CRT_PERM="$(stat -c '%a' "${CERT_DIR}/${CERT_FILE}")"
  KEY_PERM="$(stat -c '%a' "${CERT_DIR}/${KEY_FILE}")"
  [ "$CRT_PERM" -le 644 ] && ok "Cert perms OK (${CERT_FILE} ${CRT_PERM})" \
                          || warn "Cert perms loose (${CERT_FILE} ${CRT_PERM})"
  [ "$KEY_PERM" -le 600 ] && ok "Key perms OK (${KEY_FILE} ${KEY_PERM})" \
                          || bad "Key perms must be 600 or stricter (${KEY_FILE} ${KEY_PERM})"
else
  warn "Cert files not mounted in verifier; skipping permission checks (set CERT_DIR or mount volume)"
fi

ok "All checks passed 🎉"
