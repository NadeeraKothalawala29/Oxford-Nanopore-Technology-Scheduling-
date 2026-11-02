#!/usr/bin/env bash
set -euo pipefail

# Activate conda environment and local binaries
source "/home/g21_nadeera/miniconda3/etc/profile.d/conda.sh"
conda activate ont_benchmark
export PATH="$HOME/.local/bin:$PATH"

WORKSPACE="$HOME/fyp-nanopore-os-benchmark"
cd "$WORKSPACE"

echo "================================================================================"
echo " Starting Pure Unpinned Baseline Pipeline & /proc + NUMA Telemetry Profiler"
echo " Workspace: $WORKSPACE"
echo " Date (UTC): $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "================================================================================"

python3 -u "$WORKSPACE/scripts/unpinned_scheduler_profiler.py"

