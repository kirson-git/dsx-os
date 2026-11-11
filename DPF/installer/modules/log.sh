#!/usr/bin/env bash
# Command-array API: description, phase output path, executable, arguments.
log_command() {
    local description=$1 output=$2
    shift 2
    python3 "$base/tools/install_log.py" phase "$description" "$output" "$@"
}
log_message() {
    local message=$1 level=${2:-INFO}
    python3 "$base/tools/install_log.py" message "$level" "$message"
}
