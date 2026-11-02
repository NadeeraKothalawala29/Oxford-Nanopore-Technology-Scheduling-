#!/bin/bash
set -e

# Ensure conda environment (including `perf` and pipeline tools) is in PATH
export PATH="/home/g21_nadeera/miniconda3/envs/ont_benchmark/bin:/home/g21_nadeera/.local/bin:$PATH"

FLAMEGRAPH_DIR="$HOME/fyp-nanopore-os-benchmark/scripts/FlameGraph"
DEFAULT_LOG_DIR="$HOME/fyp-nanopore-os-benchmark/logs"
mkdir -p "$DEFAULT_LOG_DIR"

# Support optional --prefix <prefix> flag or LOG_PREFIX environment variable
if [ "$1" = "--prefix" ] && [ -n "$2" ]; then
    LOG_PREFIX="$2"
    shift 2
elif [ -z "${LOG_PREFIX:-}" ]; then
    LOG_PREFIX="${DEFAULT_LOG_DIR}/stage_$(date +%Y%m%d_%H%M%S)"
fi

if [ $# -eq 0 ]; then
    echo "Usage: [LOG_PREFIX=/path/to/prefix] $0 [--prefix /path/to/prefix] <command...>"
    exit 1
fi

echo "[trace_scheduler] Recording scheduler events to: ${LOG_PREFIX}_sched.data"
echo "[trace_scheduler] Target command: $*"

# 1. Record scheduler trace events
perf record -e sched:sched_switch,sched:sched_stat_wait,sched:sched_wakeup -g -o "${LOG_PREFIX}_sched.data" -- "$@"

# 2. Generate folded stacks and interactive HTML FlameGraph
perf script -i "${LOG_PREFIX}_sched.data" | "${FLAMEGRAPH_DIR}/stackcollapse-perf.pl" > "${LOG_PREFIX}_out.folded"
"${FLAMEGRAPH_DIR}/flamegraph.pl" \
    --title "OS Scheduler & Wait-Channel FlameGraph: $(basename "${LOG_PREFIX}")" \
    --subtitle "Linux CFS Scheduler States, Context Switches & Kernel Wait Channels" \
    --countname "samples" \
    "${LOG_PREFIX}_out.folded" > "${LOG_PREFIX}_sched_profile.html"

# 3. Generate human-readable scheduler latency report
perf sched latency -i "${LOG_PREFIX}_sched.data" > "${LOG_PREFIX}_latency_report.txt"

echo "[trace_scheduler] FlameGraph HTML:  ${LOG_PREFIX}_sched_profile.html"
echo "[trace_scheduler] Latency Report:   ${LOG_PREFIX}_latency_report.txt"

