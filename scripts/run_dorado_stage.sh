#!/bin/bash
set -e

INPUT_DIR="$1"
OUTPUT_FASTQ="$2"
GPU_DEVICE="${3:-cuda:1}"
CONFIG_FILE="${4:-dna_r9.4.1_450bps_fast.cfg}"

if [ -z "$INPUT_DIR" ] || [ -z "$OUTPUT_FASTQ" ]; then
    echo "Usage: $0 <input_pod5_or_fast5_dir> <output_fastq> [gpu_device] [config_file]"
    exit 1
fi

WORK_DIR="$(dirname "$OUTPUT_FASTQ")/dorado_work"
SOCK_DIR="/tmp/dorado_ipc_$$"
rm -rf "$WORK_DIR" "$SOCK_DIR"
mkdir -p "$WORK_DIR/logs" "$WORK_DIR/out" "$SOCK_DIR"

SERVER_PID=""
cleanup() {
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    rm -rf "$SOCK_DIR"
}
trap cleanup EXIT

# 1. Start Dorado Basecall Server as a child process on GPU
/opt/ont/dorado/bin/dorado_basecall_server \
    --log_path "$WORK_DIR/logs" \
    --config "$CONFIG_FILE" \
    --data_path /opt/ont/dorado/data \
    --dorado_download_path /opt/ont/dorado-models \
    --device "$GPU_DEVICE" \
    --port "$SOCK_DIR/5555" &
SERVER_PID=$!

# Wait for the IPC socket to become available
for _ in $(seq 1 100); do
    if [ -S "$SOCK_DIR/5555" ]; then
        break
    fi
    sleep 0.1
done

# 2. Run ONT Basecall Client against the server
/opt/ont/dorado/bin/ont_basecall_client \
    -i "$INPUT_DIR" \
    -s "$WORK_DIR/out" \
    -c "$CONFIG_FILE" \
    -d /opt/ont/dorado/data \
    --dorado_download_path /opt/ont/dorado-models \
    --port "ipc://$SOCK_DIR/5555" \
    -r

# 3. Combine basecalled FASTQ reads into OUTPUT_FASTQ
cat "$WORK_DIR/out/pass/"*.fastq "$WORK_DIR/out/fail/"*.fastq > "$OUTPUT_FASTQ" 2>/dev/null || true
echo "[run_dorado_stage] Wrote $(wc -l < "$OUTPUT_FASTQ") lines to $OUTPUT_FASTQ"

