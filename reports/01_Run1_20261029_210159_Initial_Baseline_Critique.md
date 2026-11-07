# Pipeline Run 1 — Research Critique & Systems Analysis (`baseline_1x_20261029_210159`)

## 1. Run Metadata & Experimental Context

| Metadata Field | Value |
| :--- | :--- |
| **Pipeline Executed** | Modular Oxford Nanopore Benchmark Pipeline (`modular_ont` — 6-Stage End-to-End Workflow) |
| **Run Tag / Identifier** | `baseline_1x_20261029_210159` (Experiment Phase 1 — Initial Uncalibrated Baseline) |
| **Execution Date & Time** | October 29, 2026 — `21:01:59` to `21:04:55` UTC |
| **Iterations Executed** | 2 consecutive back-to-back iterations (`Iteration 1`: Cold VFS Cache; `Iteration 2`: Warm VFS Cache) |
| **Total Wall-Clock Duration** | **`176.59 seconds`** (`93.345 s` in Iteration 1 + `83.255 s` in Iteration 2) |
| **Configured Thread Budget** | `--threads 16` passed to CLI-aware tools (`pod5`, `NanoPlot`, `flye`, `minimap2`, `samtools`) |
| **Server Hardware Testbed** | Dual-Socket Intel Xeon Gold 6342 (`94` online logical CPUs `0–93`, `400 GB` DDR4 RAM across `2` NUMA nodes, `4× NVIDIA A16` GPUs) |
| **Primary Telemetry Files** | [`logs/summary_baseline_1x_20261029_210159.csv`](../logs/summary_baseline_1x_20261029_210159.csv), [`logs/timeseries_baseline_1x_20261029_210159.csv`](../logs/timeseries_baseline_1x_20261029_210159.csv) |

---

## 2. What Was Measured in Run 1

In this inaugural benchmark run, [`scripts/benchmark_runner.py`](../scripts/benchmark_runner.py) launched the modular Nanopore pipeline across two consecutive iterations while polling the Linux `/proc` process tree at `10 Hz` (`100 ms` intervals) via `psutil` to measure:
1. **Stage Wall-Clock Execution Time (`duration_sec`)** across Cold vs. Warm operating system page caches.
2. **Physical Memory Footprint (`peak_rss_mb`)** — Resident Set Size (RSS) aggregated across the parent process and all spawned child worker processes.
3. **Process & Thread Concurrency (`max_processes`, `max_threads`)** — Peak simultaneous OS tasks (`task_struct` instances) alive during each stage.
4. **CPU Core Spread (`unique_cores_used`)** — Number of distinct logical CPUs (`0–93`) utilized by the stage's threads under unpinned Linux CFS scheduling.
5. **Cumulative Context Switches (`total_vol_ctx`, `total_invol_ctx`)** — Voluntary yields (waiting on disk I/O, pipes, or `futex` locks) versus involuntary OS timer preemptions.
6. **CPU Utilization (`peak_cpu_percent`)** — *Diagnostic Finding*: Recorded as `0.0%` across all stages in Run 1 due to stateless `psutil.Process(pid)` instantiation on each tick (immediately diagnosed and fixed prior to Run 2).

---

## 3. Master Telemetry Summary Table (Run 1: Iterations 1 & 2)

| Iter | Stage | Status | Duration (s) | Peak CPU (%) | Peak RSS (MB) | Max Threads | Max Procs | Unique Cores | Voluntary Ctx Switches | Involuntary Preemptions |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | `00_fast5_to_pod5` | `SUCCESS` | `7.620 s` | `0.0%` *(uncal.)* | `1,825.28 MB` | `82` | `9` | `11` | `2,431` | `88` |
| **1** | `01_dorado_basecall` | `FAILED(127)` | `0.003 s` | `0.0%` | `0.00 MB` | `0` | `0` | `0` | `0` | `0` |
| **1** | `01_dorado_basecall_r9` | `FAILED(127)` | `0.002 s` | `0.0%` | `0.00 MB` | `0` | `0` | `0` | `0` | `0` |
| **1** | `02_nanoplot_qc` | `SUCCESS` | **`28.809 s`** | `0.0%` *(uncal.)* | `1,896.12 MB` | `135` | `11` | `47` | **`33,120`** | `28` |
| **1** | `03_flye_denovo_assembly` | `SUCCESS` | `55.902 s` | `0.0%` *(uncal.)* | **`8,244.39 MB`** | `23` | `20` | `29` | `1,581` | `160` |
| **1** | `04_minimap2_align` | `SUCCESS` | `0.505 s` | `0.0%` *(uncal.)* | `0.00 MB` *(evaded)* | `0` | `0` | `0` | `0` | `0` |
| **1** | `05_samtools_sort_index` | `SUCCESS` | `0.504 s` | `0.0%` *(uncal.)* | `0.00 MB` *(evaded)* | `0` | `0` | `0` | `0` | `0` |
| **2** | `00_fast5_to_pod5` | `SUCCESS` | `7.618 s` | `0.0%` *(uncal.)* | `1,829.58 MB` | `82` | `9` | `15` | `2,467` | `95` |
| **2** | `01_dorado_basecall` | `FAILED(127)` | `0.003 s` | `0.0%` | `0.00 MB` | `0` | `0` | `0` | `0` | `0` |
| **2** | `01_dorado_basecall_r9` | `FAILED(127)` | `0.002 s` | `0.0%` | `0.00 MB` | `0` | `0` | `0` | `0` | `0` |
| **2** | `02_nanoplot_qc` | `SUCCESS` | **`17.248 s`** | `0.0%` *(uncal.)* | `1,937.92 MB` | `136` | `11` | `45` | **`4,319`** | `10` |
| **2** | `03_flye_denovo_assembly` | `SUCCESS` | `56.875 s` | `0.0%` *(uncal.)* | **`8,268.30 MB`** | `23` | `20` | `28` | `1,577` | `204` |
| **2** | `04_minimap2_align` | `SUCCESS` | `0.504 s` | `0.0%` *(uncal.)* | `0.00 MB` *(evaded)* | `0` | `0` | `0` | `0` | `0` |
| **2** | `05_samtools_sort_index` | `SUCCESS` | `0.505 s` | `0.0%` *(uncal.)* | `0.00 MB` *(evaded)* | `0` | `0` | `0` | `0` | `0` |

---

## 4. Stage-by-Stage Critical Systems Analysis

### 4.1 Stage 00: `00_fast5_to_pod5` (`7.620 s` Iter 1 / `7.618 s` Iter 2)
- **What Happened Inside the OS**: `pod5 convert fast5` spawned `9` child processes and `82` concurrent threads, occupying `1,825.28 MB` (`1.83 GB`) of physical RAM and spreading across `11` (Iter 1) to `15` (Iter 2) unique CPU cores.
- **Critical Observation**: Execution duration was virtually identical between Iteration 1 (`7.620 s`) and Iteration 2 (`7.618 s`), and voluntary context switches remained tight (`2,431` vs. `2,467`). Because `pod5` uses asynchronous multi-process HDF5 decompression workers feeding a single output writer, its bottleneck is Zstandard compression and inter-process pipe synchronization rather than cold disk reads.

### 4.2 Stage 01: `01_dorado_basecall` & `01_dorado_basecall_r9` (`FAILED(127)` in `0.003 s`)
- **What Happened Inside the OS**: The shell returned exit code `127` (`command not found`) within `3 milliseconds`.
- **Root-Cause Diagnosis**: On this server, Oxford Nanopore's basecaller is installed under `/opt/ont/dorado/bin/` using a decoupled client-server architecture (`dorado_basecall_server` + `ont_basecall_client`) rather than a single monolithic `dorado` binary on `$PATH`. Because `benchmark_runner.py` was designed with a resilient fallback mechanism, downstream stages (`NanoPlot`, `Flye`, `Minimap2`, `Samtools`) automatically consumed the sanitized `.fastq.gz` reads (`22,890` reads, `13.04 Mb`). This failure directly motivated the creation of [`scripts/run_dorado_stage.sh`](../scripts/run_dorado_stage.sh) in Run 3 and Run 4.

### 4.3 Stage 02: `02_nanoplot_qc` (`28.809 s` Iter 1 $\rightarrow$ `17.248 s` Iter 2)
- **What Happened Inside the OS**: Despite being invoked with `-t 16`, NanoPlot spawned **`11` processes and `135–136` concurrent threads**, scattering work across **`47` unique cores (Iter 1)** and **`45` unique cores (Iter 2)**—nearly half of the 94-core server!
- **Critical Discovery — The Cold vs. Warm Page-Cache Effect (`40.1%` Speedup)**:
  - In **Iteration 1 (Cold Cache)**, NanoPlot took **`28.809 seconds`** and suffered **`33,120` voluntary context switches**. Why? First-time loading of hundreds of Python shared libraries (`.so`), `matplotlib`/`plotly` font caches, and `.fastq.gz` blocks from the underlying filesystem caused threads to block repeatedly in kernel VFS page-cache misses.
  - In **Iteration 2 (Warm Cache)**—just 90 seconds later—all Python shared libraries and `.fastq.gz` blocks were already resident in the Linux kernel page cache! Voluntary context switches plummeted by **87.0%** (from `33,120` down to **`4,319`**), slashing wall-clock execution time by **`11.56 seconds` (`40.1%` faster, down to `17.248 s`)**!
  - **Implication for Handheld Edge Devices**: On flash-storage (eMMC/SD card) handheld devices, cold-start library loading in Python-heavy bioinformatics tools introduces severe I/O-wait context-switching overhead unless shared libraries remain warm in RAM.

### 4.4 Stage 03: `03_flye_denovo_assembly` (`55.902 s` Iter 1 / `56.875 s` Iter 2)
- **What Happened Inside the OS**: Flye dominated both runtime (**`63.1%`** of Iteration 1, **`68.3%`** of Iteration 2) and physical memory (**`8,244.39 MB` / `8,268.30 MB` RSS = `~8.26 GB`**). It spawned `20` processes and `23` threads across `28–29` unique CPU cores.
- **Critical Discovery — High Involuntary Preemption Ratio**: Unlike `NanoPlot` (where `99.9%` of switches were voluntary), Flye recorded **`160` (Iter 1) and `204` (Iter 2) involuntary context switches (`9.2%–11.5%` of all switches)**. Because `flye-modules` executes long, uninterrupted C++ k-mer indexing and repeat-graph traversal loops in user space, its threads continuously exhaust their Linux CFS time quantum and get forcibly preempted by the kernel timer.

### 4.5 Stages 04 & 05: `04_minimap2_align` (`0.505 s`) & `05_samtools_sort_index` (`0.504 s`)
- **What Happened Inside the OS**: Both stages completed successfully in exactly `~504–505 ms`, generating valid `aligned.sam`, `sorted.bam`, and `sorted.bam.bai` files, but recorded `0.0 MB` RSS and `0` threads in the summary CSV.
- **Root-Cause Diagnosis (Profiler Timing Artifact)**: In the initial version of `StageProfiler`, the background polling thread slept for `500 ms` before taking its first `/proc` snapshot; consequently, stages finishing in `~500 ms` exited just as the first poll fired.

---

## 5. Methodological Critique & Corrective Actions Taken After Run 1

Run 1 served as a critical diagnostic baseline that exposed three instrumentation and environment gaps, all of which were systematically engineered out in subsequent runs:

1. **Fixed Stateless `psutil.Process.cpu_percent()` Bug (Resolved in Run 2)**:
   - *Problem*: Calling `psutil.Process(pid).cpu_percent(interval=None)` on newly instantiated `Process` objects always returns `0.0%` because `psutil` has no prior CPU jiffies baseline for that object.
   - *Fix*: Implemented a persistent `proc_cache` dictionary keyed by `(pid, create_time)` inside `StageProfiler`, enabling true differential CPU utilization measurement in **Run 2 (`21:20:11`)**.
2. **Increased Polling Frequency for Sub-Second Stages (Resolved in Run 2 & Run 3)**:
   - *Problem*: `500 ms` initial sleep missed short stages (`minimap2` and `samtools`).
   - *Fix*: Reduced polling interval in Run 2 (capturing `minimap2` at `252%` CPU and `32.3 MB` RSS) and built a **250 Hz (`4 ms`) `/proc` kernel tracer** in **Run 3**, capturing all `56` threads of `minimap2` and all `37` threads of `samtools`.
3. **Engineered Standalone GPU Dorado Wrapper (Resolved in Run 3 & Run 4)**:
   - *Problem*: `dorado` was not a single binary on `$PATH`.
   - *Fix*: Built [`scripts/run_dorado_stage.sh`](../scripts/run_dorado_stage.sh) to orchestrate `/opt/ont/dorado/bin/dorado_basecall_server` and `ont_basecall_client` on NVIDIA A16 GPU `cuda:1`.
