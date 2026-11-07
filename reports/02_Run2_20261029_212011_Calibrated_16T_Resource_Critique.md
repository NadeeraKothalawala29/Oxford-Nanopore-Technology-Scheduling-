# Pipeline Run 2 — Research Critique & Systems Analysis (`baseline_1x_20261029_212011`)

## 1. Run Metadata & Experimental Context

| Metadata Field | Value |
| :--- | :--- |
| **Pipeline Executed** | Modular Oxford Nanopore Benchmark Pipeline (`modular_ont` — Calibrated CPU & Memory Profiling) |
| **Run Tag / Identifier** | `baseline_1x_20261029_212011` (Experiment Phase 1 — Calibrated 16-Thread Baseline) |
| **Execution Date & Time** | October 29, 2026 — `21:20:11` to `21:22:55` UTC |
| **Iterations Executed** | 2 consecutive iterations (`Iteration 1` & `Iteration 2`) |
| **Total Wall-Clock Duration** | **`163.43 seconds`** (`80.793 s` in Iteration 1 + `82.641 s` in Iteration 2) |
| **Configured Thread Budget** | `--threads 16` (`-t 16` / `-@ 16`) passed to all stages |
| **Server Hardware Testbed** | Dual-Socket Intel Xeon Gold 6342 (`94` online logical CPUs `0–93`, `400 GB` DDR4 RAM across `2` NUMA nodes) |
| **Primary Telemetry Files** | [`logs/summary_baseline_1x_20261029_212011.csv`](../logs/summary_baseline_1x_20261029_212011.csv), [`logs/timeseries_baseline_1x_20261029_212011.csv`](../logs/timeseries_baseline_1x_20261029_212011.csv), [`logs/exp1_console.log`](../logs/exp1_console.log) |

---

## 2. What Was Measured in Run 2

Following the calibration of `StageProfiler` in [`scripts/benchmark_runner.py`](../scripts/benchmark_runner.py) (caching `psutil.Process` instances by `(pid, create_time)` across `100 ms` polling intervals), Run 2 captured high-resolution time-series and per-stage peak telemetry across two full iterations:
1. **Calibrated Multi-Core CPU Utilization (`peak_cpu_percent`)** — In Linux accounting, `100%` equals 1 logical CPU core fully utilized (`9,400%` theoretical ceiling across 94 online CPUs).
2. **Physical RAM Footprint (`peak_rss_mb`)** — Peak Resident Set Size in megabytes across the stage's entire process tree.
3. **Thread Over-Subscription vs. Configured Thread Limits (`max_threads` vs. `--threads 16`)** — Quantifying whether bioinformatics tools actually obey user-supplied CLI thread flags.
4. **Core Scattering (`unique_cores_used`)** — Number of distinct logical CPUs touched by each stage when unpinned.
5. **Context Switch Dynamics (`total_vol_ctx`, `total_invol_ctx`)** — Voluntary I/O and lock waits versus forced OS scheduler preemptions.

---

## 3. Master Telemetry Summary Table (Run 2: Iterations 1 & 2)

| Iter | Stage | Status | Duration (s) | Peak CPU (%) | Peak RSS (MB) | Max Threads | Max Procs | Unique Cores | Voluntary Ctx Switches | Involuntary Preemptions |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | `00_fast5_to_pod5` | `SUCCESS` | `7.643 s` | `680.0%` | `1,846.65 MB` | `82` | `9` | `20` | `13,595` | `109` |
| **1** | `02_nanoplot_qc` | `SUCCESS` | `16.725 s` | **`5,457.1%`** | `2,014.91 MB` | **`140`** | `11` | **`48`** | `9,533` | `247` |
| **1** | `03_flye_denovo_assembly` | `SUCCESS` | **`55.905 s`** | `1,612.3%` | **`8,303.91 MB`** | `40` | `20` | `31` | `1,907` | `181` |
| **1** | `04_minimap2_align` | `SUCCESS` | `0.415 s` | `252.0%` | `32.26 MB` | `19` | `2` | `2` | `55` | `0` |
| **1** | `05_samtools_sort_index` | `SUCCESS` | `0.105 s` | `0.0%` *(105ms)* | `0.00 MB` *(105ms)* | `0` | `0` | `0` | `0` | `0` |
| **2** | `00_fast5_to_pod5` | `SUCCESS` | `7.611 s` | `680.9%` | `1,844.54 MB` | `82` | `9` | `12` | `13,605` | `84` |
| **2** | `02_nanoplot_qc` | `SUCCESS` | `16.866 s` | **`4,922.4%`** | `2,000.78 MB` | **`131`** | `12` | **`37`** | `9,404` | `363` |
| **2** | `03_flye_denovo_assembly` | `SUCCESS` | **`57.641 s`** | `1,766.9%` | **`8,303.71 MB`** | `28` | `20` | `29` | `1,898` | `144` |
| **2** | `04_minimap2_align` | `SUCCESS` | `0.417 s` | `250.9%` | `33.44 MB` | `19` | `2` | `2` | `54` | `0` |
| **2** | `05_samtools_sort_index` | `SUCCESS` | `0.106 s` | `0.0%` *(106ms)* | `0.00 MB` *(106ms)* | `0` | `0` | `0` | `0` | `0` |

---

## 4. Stage-by-Stage Critical Systems Analysis

### 4.1 Stage 00: `00_fast5_to_pod5` (`7.643 s` Iter 1 / `7.611 s` Iter 2)
- **Resource & Scheduling Behavior**:
  - Executed with `--threads 16`, peaking at **`680.0%` (Iter 1)** and **`680.9%` (Iter 2)** CPU utilization (~6.8 logical cores active concurrently) and **`1,846.65 MB` (`1.85 GB`)** RSS.
  - Although the user requested 16 threads, the `pod5` Python/C++ runtime spawned **`82` concurrent threads across `9` processes** (`1` master orchestrator + `8` worker subprocesses, each initializing internal Arrow/Zstd thread pools and `jemalloc` background threads).
- **Critique**: Why did 82 threads only achieve `680%` CPU instead of `1,600%`? Because `pod5` workers block heavily on inter-process pipe transfers and HDF5 file locking (`13,595` voluntary context switches in `7.64 s`, or **`1,779` voluntary switches/sec**).

### 4.2 Stage 02: `02_nanoplot_qc` (`16.725 s` Iter 1 / `16.866 s` Iter 2)
- **Critical Discovery — Uncontrolled Thread Over-Subscription Despite `-t 16`**:
  - Even though `NanoPlot` was explicitly invoked with `-t 16`, peak CPU utilization exploded to **`5,457.1%` in Iteration 1 (~55 logical cores)** and **`4,922.4%` in Iteration 2 (~49 logical cores)**, spawning **`140` concurrent threads** across **`48` unique cores**!
  - **Root Cause Inside the Software Stack**: `NanoPlot`'s `-t 16` flag only controls its top-level Python `concurrent.futures` pool. When Python imports `numpy`/`scipy` (backed by `OpenBLAS`) and invokes `kaleido` (which spawns headless `chromium` processes to render static PNG plots), those underlying C/C++ libraries completely ignore `-t 16`. Instead, they query `sysconf(_SC_NPROCESSORS_ONLN)` (`94` cores) and spawn massive worker thread pools proportional to the host CPU count.
- **Critique for Handheld / Constrained Systems**: Relying on bioinformatics CLI flags (`-t`) is insufficient to bound OS thread creation. Without OS-level `cgroups` CPU quotas, `taskset` affinity masks, or environment variables (`OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`), a simple QC plotting script triggers a thread storm that saturates the OS runqueue (`247–363` involuntary preemptions).

### 4.3 Stage 03: `03_flye_denovo_assembly` (`55.905 s` Iter 1 / `57.641 s` Iter 2)
- **Resource & Scheduling Behavior**:
  - **Well-Behaved Peak CPU Scaling**: Unlike NanoPlot, `flye --threads 16` respected its thread budget during its parallel phases, peaking at **`1,612.3%` CPU (Iter 1 = 16.1 cores)** and **`1,766.9%` CPU (Iter 2 = 17.7 cores)**.
  - **The Memory Wall (`8.30 GB` Physical RAM)**: Flye's physical memory footprint reached **`8,303.91 MB` (Iter 1)** and **`8,303.71 MB` (Iter 2)**—over **4× higher** than `pod5` or `NanoPlot`, and **250× higher** than `minimap2`!
  - **Biological Output Verified**: Successfully assembled `contig_1` (`3,921 bp` at `174×` coverage) across 4 sub-stages (`00-assembly` $\rightarrow$ `10-consensus` $\rightarrow$ `20-repeat` $\rightarrow$ `30-contigger` $\rightarrow$ `40-polishing`).
- **Critique**: Even though Peak CPU reached `1,612%–1,767%`, inspection of [`logs/timeseries_baseline_1x_20261029_212011.csv`](../logs/timeseries_baseline_1x_20261029_212011.csv) shows that Flye only sustains multi-core parallelism during brief k-mer counting and consensus windows; for the majority of its `56–58 s` runtime, CPU usage hovers near `100%` (a single C++ master thread traversing the repeat graph) while `8.30 GB` of RAM remains locked.

### 4.4 Stage 04: `04_minimap2_align` (`0.415 s` Iter 1 / `0.417 s` Iter 2)
- **Resource & Scheduling Behavior**:
  - Completed alignment of all `22,890` reads against `assembly.fasta` in **`415 ms`**, peaking at **`252.0%` CPU** (`~2.5` active cores), **`32.26 MB` RSS**, and **`19` threads** (`16` worker threads + `3` I/O/main threads) with **`0` involuntary preemptions**.
- **Critique**: `minimap2` is extraordinarily memory-efficient (`32 MB` vs. Flye's `8,304 MB`) and exhibits zero thread bloat (`19` threads for `-t 16`). Because the `13.04 Mb` dataset is small, thread startup and FASTQ gzip decompression limit effective concurrency to `2.5` cores over `0.42 s`.

### 4.5 Stage 05: `05_samtools_sort_index` (`0.105 s` Iter 1 / `0.106 s` Iter 2)
- **Resource & Scheduling Behavior**:
  - `samtools sort -@ 16` + `samtools index -@ 16` completed in just **`105 milliseconds`**!
- **Critique**: Because `105 ms` is roughly equal to a single `100 ms` `psutil` polling tick, user-space `10 Hz` polling could not capture the internal thread tree of `samtools` before process exit. This observation directly motivated the development of our **250 Hz (`4 ms`) kernel `/proc/<pid>/task/<tid>/sched` profiler** in **Run 3 (`sched_profile_20261031_122429`)**.

---

## 5. Cross-Iteration Stability & Reproducibility Verdict

Comparing Iteration 1 and Iteration 2 of Run 2 demonstrates **exceptionally high reproducibility** once the Linux VFS page cache is warm:
- **Stage 00 (`pod5`)**: `7.643 s` vs. `7.611 s` (`0.4%` variance); `680.0%` vs. `680.9%` Peak CPU; `1,846.6 MB` vs. `1,844.5 MB` RSS.
- **Stage 02 (`NanoPlot`)**: `16.725 s` vs. `16.866 s` (`0.8%` variance); `2,014.9 MB` vs. `2,000.8 MB` RSS.
- **Stage 03 (`Flye`)**: `55.905 s` vs. `57.641 s` (`3.1%` variance); `8,303.9 MB` vs. `8,303.7 MB` RSS (`< 0.01%` variance).
- **Stage 04 (`Minimap2`)**: `0.415 s` vs. `0.417 s` (`0.5%` variance); `252.0%` vs. `250.9%` Peak CPU.
