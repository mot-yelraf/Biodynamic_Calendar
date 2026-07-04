# Shared install logging helpers for Bash-based installers.

install_log_step() {
  printf '\n==> [%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

install_log_exit() {
  local status="$1"
  if [[ "$status" -eq 0 ]]; then
    install_log_step "Install completed successfully"
  else
    install_log_step "Install failed with exit status $status"
  fi

  if [[ -n "${INSTALL_LOG_TEE_PID:-}" ]]; then
    exec 1>&3 2>&4
    wait "$INSTALL_LOG_TEE_PID" 2>/dev/null || true
    exec 3>&- 4>&-
  fi
}

install_log_first_readable() {
  local path value
  for path in "$@"; do
    if [[ -r "$path" ]]; then
      value="$(tr -d '\0' < "$path" | awk 'NF {sub(/^[[:space:]]+/, ""); sub(/[[:space:]]+$/, ""); print; exit}' || true)"
      if [[ -n "$value" ]]; then
        printf '%s' "$value"
        return
      fi
    fi
  done
  printf 'unknown'
}

install_log_os_name() {
  if [[ -r /etc/os-release ]]; then
    (
      . /etc/os-release
      printf '%s' "${PRETTY_NAME:-${NAME:-Linux} ${VERSION_ID:-}}"
    )
  elif command -v sw_vers >/dev/null 2>&1; then
    printf '%s %s (%s)' \
      "$(sw_vers -productName 2>/dev/null || printf 'macOS')" \
      "$(sw_vers -productVersion 2>/dev/null || printf 'unknown')" \
      "$(sw_vers -buildVersion 2>/dev/null || printf 'unknown')"
  else
    uname -s 2>/dev/null || printf 'unknown'
  fi
}

install_log_prepare_hardware_context() {
  INSTALL_LOG_SYSTEM_PROFILER_DATA=""
  if command -v system_profiler >/dev/null 2>&1; then
    if command -v sysctl >/dev/null 2>&1 &&
      sysctl -n hw.model >/dev/null 2>&1 &&
      sysctl -n machdep.cpu.brand_string >/dev/null 2>&1 &&
      sysctl -n hw.memsize >/dev/null 2>&1; then
      return
    fi
    INSTALL_LOG_SYSTEM_PROFILER_DATA="$(system_profiler SPHardwareDataType 2>/dev/null || true)"
  fi
}

install_log_system_profiler_value() {
  local key="$1"
  if [[ -n "${INSTALL_LOG_SYSTEM_PROFILER_DATA:-}" ]]; then
    awk -F': ' -v key="$key" '$1 ~ "^[[:space:]]*" key "$" {print $2; exit}' <<< "$INSTALL_LOG_SYSTEM_PROFILER_DATA"
  fi
}

install_log_model() {
  if command -v sysctl >/dev/null 2>&1; then
    local model
    model="$(sysctl -n hw.model 2>/dev/null || true)"
    if [[ -n "$model" ]]; then
      printf '%s' "$model"
      return
    fi
  fi
  local model_name model_id
  model_name="$(install_log_system_profiler_value "Model Name")"
  model_id="$(install_log_system_profiler_value "Model Identifier")"
  if [[ -n "$model_name" && -n "$model_id" ]]; then
    printf '%s (%s)' "$model_name" "$model_id"
    return
  fi
  if [[ -n "$model_name" || -n "$model_id" ]]; then
    printf '%s' "${model_name:-$model_id}"
    return
  fi
  install_log_first_readable \
    /sys/devices/virtual/dmi/id/product_name \
    /sys/firmware/devicetree/base/model
}

install_log_cpu() {
  if command -v sysctl >/dev/null 2>&1; then
    local cpu
    cpu="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)"
    if [[ -n "$cpu" ]]; then
      printf '%s' "$cpu"
      return
    fi
  fi
  local chip cores processor_name
  chip="$(install_log_system_profiler_value "Chip")"
  cores="$(install_log_system_profiler_value "Total Number of Cores")"
  processor_name="$(install_log_system_profiler_value "Processor Name")"
  if [[ -n "$chip" || -n "$processor_name" ]]; then
    printf '%s' "${chip:-$processor_name}"
    if [[ -n "$cores" ]]; then
      printf '; %s cores' "$cores"
    fi
    return
  fi
  if [[ -r /proc/cpuinfo ]]; then
    awk -F: '/model name|Hardware|Processor/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}' /proc/cpuinfo
  else
    printf 'unknown'
  fi
}

install_log_memory() {
  if command -v sysctl >/dev/null 2>&1; then
    local bytes
    bytes="$(sysctl -n hw.memsize 2>/dev/null || true)"
    if [[ "$bytes" =~ ^[0-9]+$ ]]; then
      awk -v bytes="$bytes" 'BEGIN {printf "%.1f GiB (%s bytes)", bytes / 1024 / 1024 / 1024, bytes}'
      return
    fi
  fi
  local memory
  memory="$(install_log_system_profiler_value "Memory")"
  if [[ -n "$memory" ]]; then
    printf '%s' "$memory"
    return
  fi
  if [[ -r /proc/meminfo ]]; then
    awk '/MemTotal/ {printf "%.1f GiB (%s kB)", $2 / 1024 / 1024, $2; exit}' /proc/meminfo
  else
    printf 'unknown'
  fi
}

install_log_free_disk() {
  local target="$1"
  df -Pk "$target" 2>/dev/null | awk 'NR == 2 {printf "%.1f GiB free on %s mounted at %s", $4 / 1024 / 1024, $1, $6; exit}'
}

install_log_tool_version() {
  local label="$1"
  local tool="$2"
  shift 2

  printf '%s: ' "$label"
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'not found\n'
    return
  fi

  local output
  output="$("$tool" "$@" 2>&1 | awk 'NF {print; exit}' || true)"
  if [[ -n "$output" ]]; then
    printf '%s\n' "$output"
  else
    printf 'available at %s\n' "$(command -v "$tool")"
  fi
}

install_log_mosquitto_version() {
  printf 'mosquitto: '
  if ! command -v mosquitto >/dev/null 2>&1; then
    printf 'not found\n'
    return
  fi

  local output
  output="$(mosquitto -h 2>&1 |
    awk 'match($0, /mosquitto version [^[:space:]]+/) {print substr($0, RSTART, RLENGTH); found = 1; exit} NF && !found {first = $0} END {if (!found && first) print first}' || true)"
  if [[ -n "$output" ]]; then
    printf '%s\n' "$output"
  else
    printf 'available at %s\n' "$(command -v mosquitto)"
  fi
}

install_log_git_context() {
  local app_dir="$1"
  if ! git -C "$app_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf 'Source repo: not a git worktree\n'
    printf 'Branch: unknown\n'
    printf 'Revision: unknown\n'
    printf 'Worktree state: unknown\n'
    return
  fi

  local branch revision status
  branch="$(git -C "$app_dir" branch --show-current 2>/dev/null || true)"
  revision="$(git -C "$app_dir" rev-parse --short HEAD 2>/dev/null || true)"
  status="$(git -C "$app_dir" status --short 2>/dev/null || true)"

  printf 'Branch: %s\n' "${branch:-detached}"
  printf 'Revision: %s\n' "${revision:-unknown}"
  if [[ -n "$status" ]]; then
    printf 'Worktree state:\n%s\n' "$status"
  else
    printf 'Worktree state: clean\n'
  fi
}

install_log_header() {
  local app_dir="$1"
  local venv_dir="$2"
  local requirements="$3"
  local selected_options="$4"
  local source_repo
  source_repo="$(git -C "$app_dir" config --get remote.origin.url 2>/dev/null || true)"
  if [[ -z "$source_repo" ]]; then
    source_repo="$app_dir"
  fi

  install_log_prepare_hardware_context

  printf 'BD Calendar install log\n'
  printf 'Generated: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  printf 'Install log: %s\n' "$INSTALL_LOG"
  printf '\nSystem context\n'
  printf 'Hostname: %s\n' "$(hostname 2>/dev/null || printf 'unknown')"
  printf 'User: %s\n' "$(id -un 2>/dev/null || whoami 2>/dev/null || printf 'unknown')"
  printf 'Working dir: %s\n' "$(pwd)"
  printf 'OS name/version: %s\n' "$(install_log_os_name)"
  printf 'Kernel: %s\n' "$(uname -sr 2>/dev/null || printf 'unknown')"
  printf 'Platform/arch: %s/%s\n' "$(uname -s 2>/dev/null || printf 'unknown')" "$(uname -m 2>/dev/null || printf 'unknown')"
  printf 'Hardware model: %s\n' "$(install_log_model)"
  printf 'CPU: %s\n' "$(install_log_cpu)"
  printf 'Memory: %s\n' "$(install_log_memory)"
  printf 'Free disk space: %s\n' "$(install_log_free_disk "$app_dir")"
  printf '\nInstaller context\n'
  printf 'Source repo: %s\n' "$source_repo"
  printf 'Target PROJECT_DIR: %s\n' "$app_dir"
  printf 'Venv: %s\n' "$venv_dir"
  printf 'Requirements: %s\n' "$requirements"
  printf 'Selected options: %s\n' "$selected_options"
  printf '\nGit branch/revision/worktree state\n'
  install_log_git_context "$app_dir"
  printf '\nKey tool versions\n'
  install_log_tool_version 'Python 3' python3 --version
  install_log_tool_version 'Python' python --version
  install_log_tool_version 'pip' pip --version
  install_log_tool_version 'uv' uv --version
  install_log_tool_version 'git' git --version
  install_log_tool_version 'rsync' rsync --version
  install_log_tool_version 'apt' apt --version
  install_log_tool_version 'brew' brew --version
  install_log_tool_version 'systemctl' systemctl --version
  install_log_mosquitto_version
}

init_install_log() {
  local app_dir="$1"
  local venv_dir="$2"
  local requirements="$3"
  local selected_options="$4"
  local pipe_path

  INSTALL_LOG="${INSTALL_LOG:-$app_dir/install.log}"
  mkdir -p "$(dirname "$INSTALL_LOG")"
  : > "$INSTALL_LOG"

  exec 3>&1 4>&2
  if command -v tee >/dev/null 2>&1 && command -v mkfifo >/dev/null 2>&1; then
    pipe_path="$(mktemp "${TMPDIR:-/tmp}/bdca-install-log.XXXXXX")"
    rm -f "$pipe_path"
    mkfifo "$pipe_path"
    tee -a "$INSTALL_LOG" < "$pipe_path" &
    INSTALL_LOG_TEE_PID="$!"
    exec > "$pipe_path" 2>&1
    rm -f "$pipe_path"
  else
    exec >> "$INSTALL_LOG" 2>&1
  fi

  trap 'install_log_exit $?' EXIT
  install_log_header "$app_dir" "$venv_dir" "$requirements" "$selected_options"
}
