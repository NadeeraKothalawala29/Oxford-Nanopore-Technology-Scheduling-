# Oxford Nanopore Technology Scheduling & OS Benchmark

Fourth-Year Project (FYP) investigating Linux kernel OS scheduling behavior, thread concurrency, context switches, CPU core migrations, and memory access patterns during Oxford Nanopore Technologies (ONT) bioinformatics workloads.

---

## 1. System & Hardware Topology

- **Server Architecture**: Dual-socket Intel(R) Xeon(R) Gold 6342 CPU @ 2.80GHz
- **CPU Cores & Threads**: 48 physical cores / 96 hardware threads total (24 cores / 48 threads per socket; CPUs `0-93` online in container)
- **NUMA Nodes**:
  - **NUMA Node 0**: Even CPUs (`0,2,4,6,8,10,12,14...92`) + 50% system RAM
  - **NUMA Node 1**: Odd CPUs (`1,3,5,7,9,11,13,15...93`) + 50% system RAM
- **GPU Accelerator**: NVIDIA A16 (4 GPU instances of compute capability 8.6, 15 GB VRAM each)
- **Environment**: Proxmox LXC Container (`5.15.108-1-pve`), Ubuntu 22.04 LTS

---

## 2. Repository Structure

```text
├── Academic/                              # Academic materials, rubrics, presentations, notes
│   ├── assessment/                        # Assessment rubrics (CO421)
│   └── Presentations/                     # Presentation slides and project proposals
├── scripts/                               # Benchmark runner, GPU wrappers, and scheduler profiling scripts
│   ├── benchmark_runner.py                # Multi-stage ONT pipeline benchmark runner & telemetry logger
│   ├── run_exp1.sh                        # Isolated baseline benchmark runner script (Experiment 1)
│   ├── run_dorado_stage.sh                # Standalone Dorado basecaller client/server GPU wrapper
│   ├── trace_scheduler.sh                 # Kernel scheduler event tracer & FlameGraph generator wrapper
│   ├── unpinned_scheduler_profiler.py     # Unprivileged /proc + numa_maps 200ms scheduler & NUMA profiler
│   └── run_unpinned_baseline.sh           # Pure unpinned default pipeline runner & telemetry wrapper
├── logs/                                  # Benchmark telemetry, summary CSVs, latency reports & FlameGraphs
│   ├── unpinned_baseline/                 # Pure unpinned OS scheduler & NUMA telemetry outputs
│   │   ├── timeseries_scheduler_numa.csv  # 200ms time-series of thread states, migrations & NUMA pages
│   │   ├── stage_scheduler_summary.csv    # Per-stage summary of all 6 scheduling & NUMA categories
│   │   ├── stage_scheduler_summary.json   # Detailed JSON telemetry & timeline per stage
│   │   ├── core_heatmap_distribution.csv  # Per-core (0-93) execution hit distribution across stages
│   │   └── unpinned_scheduler_dashboard.html # Self-contained interactive Plotly HTML report
│   ├── summary_*.csv                      # Per-stage high-level execution summaries
│   ├── timeseries_*.csv                   # 100-250 Hz CPU, RAM, threads, and context switch telemetry
│   ├── *_latency_report.txt               # Thread-level CFS scheduler wait time, switch, and migration reports
│   └── *_sched_profile.html               # Interactive HTML FlameGraphs of OS scheduler states & wait channels
├── .gitignore                             # Excludes heavy raw datasets, BAM/FASTQ outputs, and raw trace data
└── README.md                              # Daily research log, pipeline documentation, and quick start guide
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

### 📅 Day 3: November 2, 2026 — Pure Unpinned Baseline Scheduler & NUMA Telemetry Profiling
- **NUMA & Hardware PMU Feasibility Analysis**:
  - Confirmed hardware memory stall cycles (`CYCLE_ACTIVITY.STALLS_MEM_ANY`) and cache misses require host admin/sudo permissions (`perf_event_paranoid <= 1` or `CAP_PERFMON`).
  - Verified that thread concurrency, core pinning (`taskset`), CPU migrations, and page-level NUMA memory allocation (`/proc/<pid>/numa_maps`) are 100% accessible in user space without sudo.
- **Pure Unpinned Baseline Profiler (`scripts/unpinned_scheduler_profiler.py` & `scripts/run_unpinned_baseline.sh`)**:
  - Executed the full 6-stage Nanopore pipeline in its pure, default unpinned state (`Cpus_allowed_list: 0-93`, `Mems_allowed_list: 0-1`, no `taskset`/`numactl`/custom thread flags).
  - Sampled `/proc/<pid>/task/<tid>/{stat,status}` every 200ms and `/proc/<pid>/numa_maps` every 2s across all child processes and threads, generating `logs/unpinned_baseline/unpinned_scheduler_dashboard.html`.
- **Key Unpinned Baseline Findings**:
  - **Thread Oversubscription & Futex Contention (`02_nanoplot_qc`)**: Without thread limits, OpenBLAS/Python spawned **989 threads** (up to 135 alive concurrently) across all **94 online cores (`0-93`)**, resulting in **206 core migrations**, **64 cross-NUMA socket bounces (31.1%)**, and **82.6% sequential bottleneck time** (average 97.5 sleeping threads waiting on locks).
  - **Cross-NUMA Memory Mismatch (`01_dorado_basecall` & `02_nanoplot_qc`)**: Dorado allocated **61.7% of RAM pages on NUMA Node 0** and **38.3% on NUMA Node 1**, while 88.9% of CPU execution occurred on Node 0, yielding an estimated **40.9% cross-socket remote memory access rate** (`33.8%` in NanoPlot).
  - **Default Single-Thread Bottlenecks (`03_flye_denovo_assembly` & `05_samtools_sort_index`)**: When invoked without explicit thread flags, Flye and Samtools default to single-threaded execution (`100%` sequential time), whereas `pod5` (`80.6%` parallel) and `dorado` (`60.6%` parallel) automatically spawn multi-threaded worker pools.

---

## 4. Benchmark Summary Metrics

### 4.1 Pure Unpinned Baseline (`/proc` + `numa_maps` Telemetry)

| Stage | Duration (s) | Spawned Threads | Active Cores | Parallel / Seq (%) | Core Migrations (Cross-NUMA) | Context Switches (Vol / Invol) | NUMA Mem Pages (N0 / N1 %) | Est. Remote NUMA Access |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **00_fast5_to_pod5** | 13.30s | 59 | 31 / 94 | 80.6% / 19.4% | 6 (0) | 8,186 / 93 | 94.2% / 5.8% | 5.8% |
| **01_dorado_basecall** | 52.70s | 114 | 72 / 94 | 60.6% / 39.4% | 201 (6) | 6,459,292 / 332 | 61.7% / 38.3% | **40.9%** |
| **02_nanoplot_qc** | 17.06s | **989** | **94 / 94** | 17.4% / **82.6%** | **206 (64)** | 106,266 / 320 | 74.3% / 25.7% | **33.8%** |
| **03_flye_denovo_assembly** | 62.26s | 44 | 23 / 94 | 0.0% / 100.0% | 9 (0) | 906 / 189 | 99.8% / 0.2% | 0.2% |
| **04_minimap2_align** | 0.47s | 6 | 6 / 94 | 0.0% / 100.0% | 0 (0) | 11 / 1 | 62.2% / 37.8% | 37.8% |
| **05_samtools_sort_index** | 0.50s | 2 | 2 / 94 | 0.0% / 100.0% | 0 (0) | 5 / 0 | 87.1% / 12.9% | 12.9% |

### 4.2 Configured 16-Thread Run (`sched_profile` with Kernel Wait Channels)

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

### Run Pure Unpinned Baseline & Generate `/proc` + `numa_maps` HTML Dashboard
```bash
bash scripts/run_unpinned_baseline.sh
```

### Run Configured Baseline Benchmark
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
- **Unpinned Baseline Interactive Dashboard**: `logs/unpinned_baseline/unpinned_scheduler_dashboard.html`
- **Unpinned Stage Summary (CSV/JSON)**: `logs/unpinned_baseline/stage_scheduler_summary.csv` & `.json`
- **Unpinned Core Heatmap Distribution**: `logs/unpinned_baseline/core_heatmap_distribution.csv`
- **Summary Metrics**: `logs/summary_*.csv`
- **Time-Series Telemetry**: `logs/timeseries_*.csv`
- **Latency Reports**: `logs/*_latency_report.txt`
- **Interactive FlameGraphs**: Open `logs/*_sched_profile.html` directly in any web browser.
