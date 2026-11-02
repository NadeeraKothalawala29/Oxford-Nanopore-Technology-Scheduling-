# Oxford Nanopore Technology Scheduling & OS Benchmark

Fourth-Year Project (FYP) investigating Linux kernel OS scheduling behavior, thread concurrency, context switches, CPU core migrations, and memory access patterns during Oxford Nanopore Technologies (ONT) bioinformatics workloads.

---

## 1. System & Hardware Topology

- **Server Architecture**: Dual-socket Intel(R) Xeon(R) Gold 6342 CPU @ 2.80GHz
- **CPU Cores & Threads**: 48 physical cores / 96 hardware threads total (24 cores / 48 threads per socket)
- **NUMA Nodes**:
  - **NUMA Node 0**: CPUs `0,2,4,6,8,10,12,14...92` + 50% system RAM
  - **NUMA Node 1**: CPUs `1,3,5,7,9,11,13,15...93` + 50% system RAM
- **GPU Accelerator**: NVIDIA A16 (4 GPU instances of compute capability 8.6, 15 GB VRAM each)
- **Environment**: Proxmox LXC Container (`5.15.108-1-pve`), Ubuntu 22.04 LTS

---

## 2. Repository Structure

```text
├── Academic/               # Academic materials, rubrics, presentations, notes
│   ├── assessment/         # Assessment rubrics (CO421)
│   └── Presentations/      # Presentation slides and project proposals
├── scripts/                # Benchmark runner, GPU wrappers, and scheduler profiling scripts
│   ├── benchmark_runner.py # Multi-stage ONT pipeline benchmark runner & telemetry logger
│   ├── run_exp1.sh         # Isolated baseline benchmark runner script (Experiment 1)
│   ├── run_dorado_stage.sh # Standalone Dorado basecaller client/server GPU wrapper
│   └── trace_scheduler.sh  # Kernel scheduler event tracer & FlameGraph generator wrapper
├── logs/                   # Benchmark telemetry, summary CSVs, latency reports & FlameGraphs
│   ├── summary_*.csv       # Per-stage high-level execution summaries
│   ├── timeseries_*.csv    # 100-250 Hz CPU, RAM, threads, and context switch telemetry
│   ├── *_latency_report.txt# Thread-level CFS scheduler wait time, switch, and migration reports
│   └── *_sched_profile.html# Interactive HTML FlameGraphs of OS scheduler states & wait channels
├── .gitignore              # Excludes heavy raw datasets, BAM/FASTQ outputs, and raw trace data
└── README.md               # Daily research log, pipeline documentation, and quick start guide
```

---

## 3. Daily Research & Experiment Log

### 📅 Day 1: October 29, 2026 — Dataset Sanitization, Conda Environment & Baseline Run
- **Dataset Sanitization**: Restructured dataset paths; moved all 6 `.fastq.gz` read files (`FAX38735_pass_...`) out of nested `fastq_pass` / `fast5_pass` directories directly into `datasets/fastq` and `datasets/fast5`.
- **Conda Environment Initialization**: Resolved Anaconda Terms of Service gating (`conda tos accept`) on Conda 26.9. Created the `ont_benchmark` environment with `python=3.10`, `psutil`, `nanoplot`, `flye`, `minimap2`, `samtools`, and `pod5`.
- **Telemetry Profiler Fix**: Resolved a `Peak CPU: 0.0%` issue in `StageProfiler` by implementing a `psutil.Process` instance cache keyed by `(pid, create_time)` across sampling intervals.
- **Experiment 1 Execution (`baseline_1x`)**: Executed 2 complete iterations under `nohup` in the background with 16 threads.
  - **Stage 00 (POD5 Conversion)**: Succeeded in ~7.6s, peak RAM 1.84 GB.
  - **Stage 02 (NanoPlot QC)**: Succeeded in ~16.8s, peak CPU ~5,400%, 140 threads utilized across 48 unique cores.
  - **Stage 03 (Flye Assembly)**: Succeeded in ~57s, peak RAM 8.3 GB, assembled `contig_1` (3,921 bp at 174x coverage).
  - **Stage 04 (Minimap2 Alignment)**: Succeeded in 0.42s.
  - **Stage 05 (Samtools Sort & Index)**: Succeeded in 0.11s.

---

### 📅 Day 2: October 31, 2026 — Kernel CFS Scheduler Profiling, FlameGraphs & GPU Basecalling
- **Container Environment Constraint**: Diagnosed that `/proc/sys/kernel/perf_event_paranoid` is set to `4` (Proxmox LXC container security), which restricts unprivileged hardware PMU counter access.
- **Custom CFS Scheduler Profiler**: Engineered a `perf`-compatible profiler at `/home/g21_nadeera/miniconda3/envs/ont_benchmark/bin/perf` sampling `/proc/<pid>/task/<tid>/{sched,schedstat,wchan,stat}` at 250 Hz (4 ms).
  - Captures real kernel CFS metrics: `se.sum_exec_runtime`, `se.vruntime`, PELT runqueue wait times (`se.avg.runnable_sum - se.avg.util_sum`), voluntary/involuntary context switches, CPU core migrations, and kernel wait channels (`wchan`).
- **Interactive FlameGraph Pipeline**: Integrated Brendan Gregg's `FlameGraph` (`stackcollapse-perf.pl` and `flamegraph.pl`) into `scripts/trace_scheduler.sh` to produce visual HTML graphs depicting on-CPU vs. blocked states (e.g., `futex_wait_queue_me`, `do_epoll_wait`, `do_sys_poll`).
- **Dorado GPU Basecalling Integration**: Resolved missing Dorado pathing by writing `scripts/run_dorado_stage.sh`, launching `dorado_basecall_server` and `ont_basecall_client` on `cuda:1` with model `dna_r9.4.1_e8_fast@v3.4`. Successfully basecalled 134,857,784 samples at 3.09M samples/sec.
- **Complete Profiling Run (`sched_profile`)**: Generated individual scheduler reports and HTML FlameGraphs for all 6 pipeline stages.

---

### 📅 Day 3: November 2, 2026 — NUMA Analysis Feasibility, Repository Initialization & GitHub Sync
- **NUMA & Hardware PMU Feasibility Analysis**:
  - Confirmed hardware memory stall cycles (`CYCLE_ACTIVITY.STALLS_MEM_ANY`) and cache misses require host admin/sudo permissions (`perf_event_paranoid <= 1` or `CAP_PERFMON`).
  - Verified that thread concurrency, core pinning (`taskset`), CPU migrations, and page-level NUMA memory allocation (`/proc/<pid>/numa_maps`) are fully accessible without sudo.
- **GitHub Repository Synchronization**:
  - Linked workspace to `git@github.com:NadeeraKothalawala29/Oxford-Nanopore-Technology-Scheduling-.git` via ED25519 SSH authentication.
  - Cleaned `.gitignore` to track all benchmark source scripts, academic documents, and analysis logs (`.csv`, `.html`, `.txt`) while excluding heavy multi-gigabyte raw reads and binary trace dumps (`*.data`).

---

## 4. Benchmark Summary Metrics

| Stage | Duration (s) | Peak CPU (%) | Peak RAM (MB) | Max Threads | Unique Cores | Key Kernel Wait Channels (`wchan`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **00_fast5_to_pod5** | 7.64s | 680.0% | 1,846 MB | 82 | 20 | `futex_wait_queue_me`, `do_sys_poll` |
| **01_dorado_basecall** | 43.62s | GPU (`cuda:1`) | 2,100 MB | 124 | 48 | `do_epoll_wait`, `futex_wait_queue_me`, `do_sys_poll` |
| **02_nanoplot_qc** | 16.73s | 5,457.1% | 2,014 MB | 140 | 48 | `userspace_on_cpu`, `futex_wait_queue_me` |
| **03_flye_denovo_assembly** | 55.91s | 1,612.3% | 8,303 MB | 40 | 31 | `userspace_on_cpu` (single dominant master thread) |
| **04_minimap2_align** | 0.42s | 252.0% | 32 MB | 19 | 2 | `userspace_on_cpu`, `futex_wait_queue_me` |
| **05_samtools_sort_index** | 0.11s | <0.1s | 74 MB | 22 | 8 | `userspace_on_cpu` |

---

## 5. How to Run & Profile

### Activate Environment
```bash
conda activate ont_benchmark
```

### Run Baseline Benchmark
```bash
bash scripts/run_exp1.sh
```

### Run with CFS Scheduler Tracing & Generate HTML FlameGraphs
```bash
python3 scripts/benchmark_runner.py \
    --run-tag sched_profile \
    --iterations 1 \
    --threads 16 \
    --gpu-device cuda:1 \
    --trace-scheduler
```

### Inspect Output Logs
- **Summary Metrics**: `logs/summary_*.csv`
- **Time-Series Telemetry**: `logs/timeseries_*.csv`
- **Latency Reports**: `logs/*_latency_report.txt`
- **Interactive Visualizations**: Open `logs/*_sched_profile.html` directly in any web browser.
