#!/usr/bin/env bash
#
# Install PostgreSQL client + server locally if missing (macOS Homebrew, Linux apt/yum/dnf).
# Idempotent: exits early if `psql` is already on PATH (still tries to start the service).
#
# Usage:
#   ./scripts/install_postgres_local.sh
#   DRY_RUN=1 ./scripts/install_postgres_local.sh
#
# Native packages usually listen on 5432; this project defaults to PUGSY_PG_PORT=5433 for
# Docker-style setups — set PUGSY_PG_PORT / postgresql.conf as needed.
#
set -Eeuo pipefail

readonly DRY_RUN="${DRY_RUN:-0}"
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_err() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

sudo_prefix() {
  if [[ "$(id -u)" -eq 0 ]]; then
    echo ""
  else
    echo "sudo "
  fi
}

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log_info "[DRY_RUN] $*"
    return 0
  fi
  log_info "Running: $*"
  eval "$@"
}

require_sudo_linux() {
  if [[ "$(id -u)" -eq 0 ]]; then
    return 0
  fi
  if command_exists sudo; then
    return 0
  fi
  log_err "Need root or sudo on Linux to install packages."
  exit 1
}

# --- Start / enable PostgreSQL (best-effort, idempotent) ---

start_postgres_macos() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log_info "[DRY_RUN] brew services start postgresql"
    return 0
  fi
  if ! command_exists brew; then
    log_warn "Homebrew not found; cannot auto-start PostgreSQL."
    return 0
  fi
  if brew services start postgresql 2>/dev/null; then
    log_ok "PostgreSQL service started (brew services start postgresql)."
    return 0
  fi
  local f
  for f in postgresql@17 postgresql@16 postgresql@15 postgresql@14; do
    if brew list "$f" &>/dev/null && brew services start "$f" 2>/dev/null; then
      log_ok "PostgreSQL service started (brew services start $f)."
      return 0
    fi
  done
  log_warn "Could not auto-start PostgreSQL. Try: brew services start postgresql"
}

start_postgres_linux_debian() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log_info "[DRY_RUN] systemctl enable --now postgresql"
    return 0
  fi
  local sp
  sp="$(sudo_prefix)"
  if command_exists systemctl; then
    if ${sp}systemctl enable --now postgresql 2>/dev/null; then
      log_ok "PostgreSQL started and enabled (systemd: postgresql)."
      return 0
    fi
    if ${sp}systemctl start postgresql 2>/dev/null; then
      log_ok "PostgreSQL started (systemd: postgresql)."
      return 0
    fi
    # Versioned clusters (common on Debian/Ubuntu)
    local unit
    unit="$(${sp}systemctl list-unit-files 2>/dev/null | grep -E 'postgresql@[0-9]+-main\.service' | head -1 | awk '{print $1}' || true)"
    if [[ -n "${unit:-}" ]]; then
      if ${sp}systemctl enable --now "$unit" 2>/dev/null; then
        log_ok "PostgreSQL started (systemd: $unit)."
        return 0
      fi
    fi
  fi
  if command_exists service; then
    if ${sp}service postgresql start 2>/dev/null; then
      log_ok "PostgreSQL started (service postgresql start)."
      return 0
    fi
  fi
  log_warn "Could not auto-start PostgreSQL. Try: $(sudo_prefix | tr -d ' ')systemctl start postgresql"
}

start_postgres_linux_rhel() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log_info "[DRY_RUN] postgresql-setup / systemctl enable --now postgresql"
    return 0
  fi
  local sp
  sp="$(sudo_prefix)"
  if command_exists postgresql-setup; then
    ${sp}postgresql-setup --initdb 2>/dev/null || true
  elif [[ -x /usr/pgsql-*/bin/postgresql-setup ]]; then
    for setup in /usr/pgsql-*/bin/postgresql-setup; do
      [[ -x "$setup" ]] && ${sp}"$setup" --initdb 2>/dev/null || true
    done
  fi
  if command_exists systemctl; then
    if ${sp}systemctl enable --now postgresql 2>/dev/null; then
      log_ok "PostgreSQL started and enabled (systemd)."
      return 0
    fi
    if ${sp}systemctl start postgresql 2>/dev/null; then
      log_ok "PostgreSQL started (systemd)."
      return 0
    fi
  fi
  log_warn "Could not auto-start PostgreSQL. Try: $(sudo_prefix | tr -d ' ')systemctl enable --now postgresql"
}

is_debian_like() {
  [[ -f /etc/debian_version ]] || { [[ -f /etc/os-release ]] && grep -qiE 'debian|ubuntu' /etc/os-release; }
}

is_rhel_like() {
  [[ -f /etc/redhat-release ]] || { [[ -f /etc/os-release ]] && grep -qiE 'rhel|fedora|centos|rocky|almalinux|amazon' /etc/os-release; }
}

ensure_postgres_service_running() {
  case "$(uname -s)" in
    Darwin)
      start_postgres_macos
      ;;
    Linux)
      if is_debian_like || command_exists apt-get; then
        start_postgres_linux_debian
      elif is_rhel_like || command_exists dnf || command_exists yum; then
        start_postgres_linux_rhel
      else
        log_warn "Unknown Linux family; skipping auto-start."
      fi
      ;;
    *)
      ;;
  esac
}

install_macos() {
  if ! command_exists brew; then
    log_err "Homebrew not found. Install from https://brew.sh then re-run."
    exit 1
  fi
  log_info "Installing PostgreSQL via Homebrew..."
  run "brew install postgresql"
  log_info "Default listen port is often 5432; set PUGSY_PG_PORT if your server uses another port."
}

install_linux_debian() {
  require_sudo_linux
  if [[ "$(id -u)" -eq 0 ]]; then
    run "apt-get update && apt-get install -y postgresql postgresql-contrib"
  else
    run "sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib"
  fi
  log_info "Default listen port is often 5432; set PUGSY_PG_PORT if your server uses another port."
}

install_linux_rhel() {
  require_sudo_linux
  if command_exists dnf; then
    if [[ "$(id -u)" -eq 0 ]]; then
      run "dnf install -y postgresql-server postgresql"
    else
      run "sudo dnf install -y postgresql-server postgresql"
    fi
  elif command_exists yum; then
    if [[ "$(id -u)" -eq 0 ]]; then
      run "yum install -y postgresql-server postgresql"
    else
      run "sudo yum install -y postgresql-server postgresql"
    fi
  else
    log_err "Neither dnf nor yum found."
    exit 1
  fi
  log_info "Default listen port is often 5432; set PUGSY_PG_PORT if your server uses another port."
}

main() {
  if command_exists psql; then
    log_ok "psql already on PATH ($(command -v psql))."
    ensure_postgres_service_running
    exit 0
  fi

  case "$(uname -s)" in
    Darwin)
      install_macos
      ;;
    Linux)
      if is_debian_like; then
        install_linux_debian
      elif is_rhel_like; then
        install_linux_rhel
      elif command_exists apt-get; then
        install_linux_debian
      elif command_exists dnf || command_exists yum; then
        install_linux_rhel
      else
        log_err "Unsupported Linux distribution for automatic install."
        exit 1
      fi
      ;;
    *)
      log_err "Unsupported OS: $(uname -s)"
      exit 1
      ;;
  esac

  if [[ "$DRY_RUN" != "1" ]] && command_exists psql; then
    log_ok "psql installed at $(command -v psql)"
  elif [[ "$DRY_RUN" != "1" ]]; then
    log_warn "Install finished but psql not on PATH yet; open a new shell or check package notes."
  fi
  ensure_postgres_service_running
}

main "$@"
