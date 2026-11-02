#!/bin/bash
set -e

# 1. Hardcode the Conda source path we just installed
source /home/g21_nadeera/miniconda3/etc/profile.d/conda.sh

# Then activate your environment
conda activate ont_benchmark
export PATH="$HOME/.local/bin:$PATH"

# 2. Verify dependencies before starting
echo "Python path: $(which python3)"
python3 -c "import psutil; print('psutil successfully loaded!')"

# 3. Run Experiment 1 (Isolated Baseline)
python3 -u "$HOME/fyp-nanopore-os-benchmark/scripts/benchmark_runner.py" \
    --run-tag "baseline_1x" \
    --iterations 2 \
    --threads 16 \
    --gpu-device "cuda:1" \
    --dorado-model "/opt/ont/dorado-models/dna_r10.4.1_e8.2_400bps_fast@v4.3.0"
