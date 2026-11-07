# Oxford Nanopore Technology Scheduling & OS Benchmark

Fourth-Year Project (FYP) investigating Linux kernel OS scheduling behavior, thread concurrency, context switches, CPU core migrations, and memory access patterns during Oxford Nanopore Technologies (ONT) bioinformatics workloads towards resource-constrained handheld edge devices.

---

## 1. System & Hardware Topology

All tests were performed on an enterprise multi-socket server testbed:
- **Server Architecture**: Dual-socket Intel(R) Xeon(R) Gold 6342 CPU @ 2.80GHz
- **CPU Cores & Threads**: 48 physical cores / 96 hardware threads total (24 cores / 48 threads per socket; CPUs `0-93` online in container)
- **NUMA Nodes**:
  - **NUMA Node 0**: Even CPUs (`0, 2, 4, 6, 8, 10 ... 92`) + 50% system RAM (~200 GB)
  - **NUMA Node 1**: Odd CPUs (`1, 3, 5, 7, 9, 11 ... 93`) + 50% system RAM (~200 GB)
- **GPU Accelerator**: 4× NVIDIA A16 instances (Ampere architecture, compute capability 8.6, 15 GB VRAM per die)
- **Environment**: Proxmox LXC Container (`5.15.108-1-pve`), Ubuntu 22.04 LTS, Conda environment `ont_benchmark`

---

## 2. Repository Structure

```text
├── pipelines/                             # Pipeline architectures & workflow documentation
│   └── README.md                          # Detailed breakdown of modular and community ONT pipelines
├── reports/                               # Research-level systems critique reports for each pipeline run
│   ├── README.md                          # Master cross-run comparative synthesis & index (Runs 1–4)
│   ├── 01_Run1_20261029_210159_Initial_Baseline_Critique.md
│   ├── 02_Run2_20261029_212011_Calibrated_16T_Resource_Critique.md
│   ├── 03_Run3_20261031_122429_Kernel_CFS_FlameGraph_Critique.md
│   └── 04_Run4_20261102_112000_Unpinned_CFS_NUMA_Critique.md
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
│   │   ├── unpinned_scheduler_dashboard.html # Self-contained interactive Plotly HTML report
│   │   └── *.log                          # Stage-by-stage stdout/stderr execution logs
│   ├── summary_*.csv                      # Per-stage high-level execution summaries (CPU, RAM, Time)
│   ├── timeseries_*.csv                   # 1-second interval CPU %, RAM, and I/O telemetry
│   ├── *_latency_report.txt               # Thread-level CFS scheduler wait time, switch, and migration reports
│   ├── *_sched_profile.html               # Interactive HTML FlameGraphs of OS scheduler states & wait channels
│   └── *.log                              # Historical execution logs across experimental runs
├── .gitignore                             # Excludes heavy raw datasets, BAM/FASTQ outputs, and raw trace data
└── README.md                              # Daily research log, pipeline documentation, and quick start guide
```

> **Note on Data and Code Exclusions**:
> - Raw sequencing datasets (`.fast5`, `.pod5`, `.fastq`) and large intermediate sequence alignments (`.sam`, `.bam`, `.fasta`) are excluded to keep the repository lightweight.
> - Third-party Nextflow sub-repositories (`pipelines/*`) are documented in [`pipelines/README.md`](pipelines/README.md).
> - Research-level stage-by-stage critique reports for all 4 benchmark runs are located in [`reports/`](reports/README.md).
> - All experimental telemetry, scheduler profiles, memory/NUMA distributions, and execution logs are tracked in [`logs/`](logs/).

---

## 3. Pipelines & Workflows Evaluated

Our benchmark evaluates a complete 6-stage Oxford Nanopore sequence processing pipeline representing diverse computational profiles:

1. **`00_fast5_to_pod5` (`pod5 convert fast5`)**: Converts legacy raw FAST5 ionic current files into compressed columnar POD5 format. *Compute Profile: High I/O throughput + multi-threaded Zstandard compression.*
2. **`01_dorado_basecall` (`dorado_basecall_server` on `cuda:1`)**: Neural network basecaller decoding 22,890 reads (13.04 Mb) using model `dna_r9.4.1_e8_fast@v3.4`. *Compute Profile: GPU tensor matrix multiplication + CPU queue management.*
3. **`02_nanoplot_qc` (`NanoPlot`)**: Statistical quality control, read-length distribution calculation, and graphical summary generation. *Compute Profile: Multi-core CPU bursts across mathematical libraries.*
4. **`03_flye_denovo_assembly` (`Flye`)**: De-novo repeat-graph assembly constructing genome contigs without a reference. *Compute Profile: High memory allocation (RAM RSS) and graph traversal.*
5. **`04_minimap2_align` (`minimap2 -ax map-ont`)**: Long-read seed-and-chain alignment mapping reads back to assembled contigs. *Compute Profile: Compute-bound string matching and hashing.*
6. **`05_samtools_sort_index` (`samtools sort` & `index`)**: BAM coordinate sorting and indexing. *Compute Profile: Streaming BGZF block compression.*

*For complete tool descriptions and workflow variations, see [`pipelines/README.md`](pipelines/README.md).*

---

## 4. Experimental Tests Conducted on the Server

### 🧪 Test 1: Configured 16-Thread Baseline Profiling (`sched_profile`)
- **Objective**: Profile pipeline resource consumption, runtime, CPU %, RAM RSS, and kernel wait channels when stages are executed with standard 16-thread flags.
- **Telemetry Method**: Custom 250 Hz `/proc/<pid>/task/<tid>/sched` profiler coupled with Brendan Gregg's `FlameGraph` to identify on-CPU execution vs. kernel wait channels (`wchan` like `futex_wait_queue_me`, `do_epoll_wait`).
- **Reports Generated**: `logs/summary_sched_profile_*.csv`, `logs/timeseries_sched_profile_*.csv`, `logs/*_sched_profile.html`.

### 🧪 Test 2: Pure Unpinned Linux CFS & NUMA Telemetry Profiling (`unpinned_baseline`)
- **Objective**: Profile the pure, default unpinned behavior of each tool (letting Linux CFS place threads freely across all 0–93 online cores, with zero pinning, no `taskset`, and native tool defaults) to discover organic scheduler pathologies and memory placement mismatches.
- **Telemetry Method**: Sampled `/proc/<pid>/task/<tid>/stat` (fields 3 `state` and 39 `task_cpu`) and `/proc/<pid>/task/<tid>/status` every 200 ms, plus physical page residency from `/proc/<pid>/numa_maps` every 2 seconds.
- **Reports Generated**: `logs/unpinned_baseline/stage_scheduler_summary.csv`, `logs/unpinned_baseline/core_heatmap_distribution.csv`, `logs/unpinned_baseline/unpinned_scheduler_dashboard.html`.

---

## 5. Summary Results & Telemetry Findings

### 5.1 Pure Unpinned Baseline Telemetry (`/proc` + `numa_maps`)

| Stage | Duration (s) | Spawned Threads | Active Cores | Parallel / Seq (%) | Core Migrations (Cross-NUMA) | Context Switches (Vol / Invol) | NUMA Mem Pages (N0 / N1 %) | Est. Remote NUMA Access |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **00_fast5_to_pod5** | 13.30s | 59 | 31 / 94 | 80.6% / 19.4% | 6 (0) | 8,186 / 93 | 94.2% / 5.8% | 5.8% |
| **01_dorado_basecall** | 52.70s | 114 | 72 / 94 | 60.6% / 39.4% | 201 (6) | 6,459,292 / 332 | 61.7% / 38.3% | **40.9%** |
| **02_nanoplot_qc** | 17.06s | **989** | **94 / 94** | 17.4% / **82.6%** | **206 (64)** | 106,266 / 320 | 74.3% / 25.7% | **33.8%** |
| **03_flye_denovo_assembly** | 62.26s | 44 | 23 / 94 | 0.0% / 100.0% | 9 (0) | 906 / 189 | 99.8% / 0.2% | 0.2% |
| **04_minimap2_align** | 0.47s | 6 | 6 / 94 | 0.0% / 100.0% | 0 (0) | 11 / 1 | 62.2% / 37.8% | 37.8% |
| **05_samtools_sort_index** | 0.50s | 2 | 2 / 94 | 0.0% / 100.0% | 0 (0) | 5 / 0 | 87.1% / 12.9% | 12.9% |

### 5.2 Key Scheduling, Resource & NUMA Findings

1. **Thread Explosion vs. Sequential Waiting (`02_nanoplot_qc`)**:
   - Without thread caps, OpenBLAS/NumPy and headless browser plotting workers spawned **989 threads** (up to 135 concurrent threads) across all **94 cores**.
   - Despite this massive thread burst, the stage spent **82.6% of its runtime in a sequential bottleneck** (`avg_running_threads = 1.16`), with an average of **97.5 sleeping threads** blocked on Python GIL and `futex` locks.
2. **CPU Core Migrations & Cross-Socket Bouncing**:
   - In unpinned execution, threads frequently migrate across cores upon waking from I/O or locks: **201 migrations in Dorado** and **206 migrations in NanoPlot**.
   - In NanoPlot, **64 of those migrations (31.1%) were cross-NUMA socket bounces**, moving threads between Socket 0 (even cores) and Socket 1 (odd cores), invalidating L1/L2 caches.
3. **Cross-NUMA Memory Latency Mismatch (`01_dorado_basecall`)**:
   - Due to Linux's First-Touch page allocation policy, Dorado allocated **61.7% of physical RAM pages on Node 0** and **38.3% on Node 1**, while **88.9% of CPU execution occurred on Node 0**.
   - This mismatch resulted in an estimated **40.9% remote memory access rate**, forcing memory requests across the slower inter-socket interconnect.
4. **Memory Footprint & Handheld Constraints (`03_flye_denovo_assembly`)**:
   - Flye assembly consumed **8.34 GB peak physical RAM (RSS)** and took **62.3 seconds**—demanding 4× more memory than any other stage.
   - For a portable handheld edge device with 4–8 GB total RAM, Flye's memory footprint presents the primary bottleneck, whereas streaming alignment stages (`POD5` → `Dorado` → `Minimap2` → `Samtools`) peak at only **2.1 GB RAM**.
5. **Involuntary Preemptions (`03_flye_denovo_assembly`)**:
   - Flye experienced **17.3% involuntary context switches** (189 forced preemptions vs. 906 voluntary yields), demonstrating that compute-intensive assembly threads frequently exhaust their scheduler time-slice.

---

## 6. Daily Research & Experiment Log

### 📅 Day 1: October 29, 2026 — Dataset Sanitization, Conda Environment & Baseline Run
- **Dataset Sanitization**: Restructured dataset paths; organized raw files into `datasets/fast5` and `datasets/fastq`.
- **Conda Environment Initialization**: Configured `ont_benchmark` environment with `python=3.10`, `psutil`, `nanoplot`, `flye`, `minimap2`, `samtools`, and `pod5`.
- **Telemetry Profiler Fix**: Resolved a `Peak CPU: 0.0%` issue in `StageProfiler` by implementing a `psutil.Process` instance cache keyed by `(pid, create_time)` across sampling intervals.
- **Experiment 1 Execution (`baseline_1x`)**: Executed 2 complete iterations under `nohup` in the background with 16 threads, capturing baseline runtimes and memory peaks.

### 📅 Day 2: October 31, 2026 — Kernel CFS Scheduler Profiling, FlameGraphs & GPU Basecalling
- **Container Environment Constraint**: Diagnosed that `/proc/sys/kernel/perf_event_paranoid` is set to `4` (Proxmox LXC container security), restricting unprivileged hardware PMU counter access.
- **Custom CFS Scheduler Profiler**: Engineered a `perf`-compatible profiler sampling `/proc/<pid>/task/<tid>/{sched,schedstat,wchan,stat}` at 250 Hz (4 ms).
- **Interactive FlameGraph Pipeline**: Integrated Brendan Gregg's `FlameGraph` into `scripts/trace_scheduler.sh` to produce visual HTML graphs depicting on-CPU vs. blocked states (e.g., `futex_wait_queue_me`, `do_epoll_wait`).
- **Dorado GPU Basecalling Integration**: Built `scripts/run_dorado_stage.sh`, launching `dorado_basecall_server` on `cuda:1` with model `dna_r9.4.1_e8_fast@v3.4`. Successfully basecalled 134.8M samples at 3.09M samples/sec.

### 📅 Day 3: November 2, 2026 — Pure Unpinned Baseline Scheduler & NUMA Telemetry Profiling
- **NUMA & Hardware PMU Feasibility Analysis**:
  - Confirmed hardware memory stall cycles (`CYCLE_ACTIVITY.STALLS_MEM_ANY`) require host root access.
  - Verified that thread concurrency, core pinning (`taskset`), CPU migrations, and page-level NUMA memory allocation (`/proc/<pid>/numa_maps`) are 100% accessible in user space without sudo.
- **Pure Unpinned Baseline Profiler**:
  - Executed the full 6-stage Nanopore pipeline in its pure, default unpinned state (`Cpus_allowed_list: 0-93`, `Mems_allowed_list: 0-1`).
  - Sampled `/proc/<pid>/task/<tid>/{stat,status}` every 200 ms and `/proc/<pid>/numa_maps` every 2 s across all child processes and threads, generating `logs/unpinned_baseline/unpinned_scheduler_dashboard.html`.

---

## 7. How to Run & Inspect Results

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

### Inspect Output Telemetry & Reports
- **Interactive Unpinned Dashboard**: Open `logs/unpinned_baseline/unpinned_scheduler_dashboard.html` in any web browser.
- **Stage Scheduler Telemetry**: Read `logs/unpinned_baseline/stage_scheduler_summary.csv` or `.json`.
- **Per-Core Hit Distribution**: Read `logs/unpinned_baseline/core_heatmap_distribution.csv`.
- **Continuous 200ms Timeseries**: Read `logs/unpinned_baseline/timeseries_scheduler_numa.csv`.
- **Interactive Scheduler FlameGraphs**: Open `logs/*_sched_profile.html` in any browser.
- **Scheduler Wait-Channel Reports**: Read `logs/*_latency_report.txt`.
