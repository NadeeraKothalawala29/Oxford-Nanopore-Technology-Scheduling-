# Pipeline Run 4 — Research Critique & Unpinned NUMA/CFS Analysis (`unpinned_baseline_20261102`)

## 1. Run Metadata & Experimental Context

| Metadata Field | Value |
| :--- | :--- |
| **Pipeline Executed** | Complete 6-Stage Modular Oxford Nanopore Pipeline (`modular_ont` — **Pure Unpinned Native Defaults**) |
| **Run Tag / Identifier** | `unpinned_baseline` (Experiment Phase 2B — Pure Unpinned Linux CFS & Dual-Socket NUMA Telemetry) |
| **Execution Date & Time** | November 2, 2026 — `11:20` to `11:23` UTC |
| **Total Wall-Clock Duration** | **`146.29 s`** (`13.299 s` POD5 + `52.700 s` Dorado + `17.062 s` NanoPlot + `62.262 s` Flye + `0.470 s` Minimap2 + `0.497 s` Samtools) |
| **Scheduling & Pinning Policy** | **100% Unconstrained / Unpinned** (`Cpus_allowed_list: 0-93`, `Mems_allowed_list: 0-1`; **no** `taskset`, **no** `numactl`, **no** custom `-t`/`--threads` flags) |
| **Server NUMA Architecture** | Dual-Socket Intel Xeon Gold 6342 (`94` online CPUs: **NUMA Node 0** = Even CPUs `0,2,4...92`; **NUMA Node 1** = Odd CPUs `1,3,5...93`; `400 GB` RAM) |
| **Sampling Granularity** | **`200 ms` (`5 Hz`)** `/proc/<pid>/task/<tid>/{stat,status}` thread-state & core-migration sampler + **`2.0 s`** `/proc/<pid>/numa_maps` physical page profiler |
| **Primary Telemetry & Visual Files** | [`logs/unpinned_baseline/stage_scheduler_summary.csv`](../logs/unpinned_baseline/stage_scheduler_summary.csv), [`stage_scheduler_summary.json`](../logs/unpinned_baseline/stage_scheduler_summary.json), [`core_heatmap_distribution.csv`](../logs/unpinned_baseline/core_heatmap_distribution.csv), [`timeseries_scheduler_numa.csv`](../logs/unpinned_baseline/timeseries_scheduler_numa.csv), [`unpinned_scheduler_dashboard.html`](../logs/unpinned_baseline/unpinned_scheduler_dashboard.html) |

---

## 2. What Was Measured in Run 4

In Runs 1–3, we passed explicit `--threads 16` flags to pipeline stages. In **Run 4**, we asked a fundamental operating-systems question: *What happens when a bioinformatician runs the entire 6-stage Oxford Nanopore pipeline using each tool's native defaults on an unpinned multi-socket Linux server?*

Using [`scripts/unpinned_scheduler_profiler.py`](../scripts/unpinned_scheduler_profiler.py) and [`scripts/run_unpinned_baseline.sh`](../scripts/run_unpinned_baseline.sh), we measured **6 exact kernel scheduling & NUMA dimensions** across all `735` time-series ticks:
1. **Thread Spawning & Per-Core Hit Distribution (`0–93`)** via `/proc/<pid>/task/<tid>/stat` field 39 (`task_cpu` / `psr`).
2. **Sequential Bottleneck vs. Parallel Execution Time (%)** — Classifying every `200 ms` tick by counting threads actively running on a CPU (`state == 'R'`): **Sequential** (`R <= 1`) vs. **Parallel** (`R > 1`), alongside average sleeping threads (`state == 'S'` or `'D'`).
3. **Net CPU Core Migrations & Cross-NUMA Socket Bounces** — Tracking `last_cpu[tid]` across consecutive `200 ms` ticks and counting how often a thread jumped between different cores (`total_core_migrations`) and between Socket 0 (even CPUs) and Socket 1 (odd CPUs) (`cross_numa_socket_bounces`).
4. **Voluntary vs. Involuntary Context Switches (`voluntary_switch_pct`, `involuntary_preemption_pct`)** from `/proc/<pid>/task/<tid>/status`.
5. **Physical NUMA Page Allocation (`numa_node0_mem_pct` vs. `numa_node1_mem_pct`)** by parsing `N0=<pages>` and `N1=<pages>` across all memory mappings in `/proc/<pid>/numa_maps`.
6. **CPU-to-Memory NUMA Locality & Remote Access Penalty (`estimated_numa_remote_access_pct`)** — Combining per-socket CPU execution residency with per-socket RAM page residency:
   $$\text{Remote NUMA Access \%} = \left(P_{\text{CPU}_0} \times P_{\text{MEM}_1}\right) + \left(P_{\text{CPU}_1} \times P_{\text{MEM}_0}\right)$$

---

## 3. Master Telemetry Summary Table (Run 4: Pure Unpinned Baseline)

| Stage | Duration (s) | Spawned Threads (Max Alive) | Active Cores (`/94`) | Parallel vs. Sequential (%) | Avg Running / Avg Sleeping Threads | Core Migrations (`200ms` Net) | Cross-Socket Bounces (`%`) | Context Switches (`Vol / Invol`) | Involuntary Preemption (%) | NUMA RAM (`N0 / N1 %`) | NUMA CPU (`N0 / N1 %`) | Est. Remote NUMA Access (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`00_fast5_to_pod5`** | `13.299 s` | `59` (`59`) | `31 / 94` | **`80.6%`** / `19.4%` | `2.85` / `41.64` | `6` | `0` (`0.0%`) | `8,186 / 93` | `1.12%` | `94.2% / 5.8%` | `100.0% / 0.0%` | `5.82%` |
| **`01_dorado_basecall`** | `52.700 s` | `114` (`96`) | `72 / 94` | **`60.6%`** / `39.4%` | `1.92` / **`85.53`** | **`201`** | `6` (`2.99%`) | **`6,459,292 / 332`** | `0.01%` | `61.7% / 38.3%` | `88.9% / 11.1%` | **`40.87%`** |
| **`02_nanoplot_qc`** | `17.062 s` | **`989`** (`135`) | **`94 / 94`** | `17.4%` / **`82.6%`** | `1.16` / **`97.53`** | **`206`** | **`64` (`31.07%`)** | `106,266 / 320` | `0.30%` | `74.3% / 25.7%` | `83.2% / 16.8%` | **`33.84%`** |
| **`03_flye_denovo_assembly`** | **`62.262 s`** | `44` (`11`) | `23 / 94` | `0.0%` / **`100.0%`** | `1.00` / `1.32` | `9` | `0` (`0.0%`) | `906 / 189` | **`17.26%`** | `99.8% / 0.2%` | `100.0% / 0.0%` | `0.17%` |
| **`04_minimap2_align`** | `0.470 s` | `6` (`3`) | `6 / 94` | `0.0%` / **`100.0%`** | `1.00` / `1.67` | `0` | `0` (`0.0%`) | `11 / 1` | **`8.33%`** | `62.2% / 37.8%` | `100.0% / 0.0%` | **`37.83%`** |
| **`05_samtools_sort_index`** | `0.497 s` | `2` (`1`) | `2 / 94` | `0.0%` / **`100.0%`** | `0.67` / `0.33` | `0` | `0` (`0.0%`) | `5 / 0` | `0.00%` | `87.1% / 12.9%` | `100.0% / 0.0%` | `12.93%` |

---

## 4. Stage-by-Stage Research Critique & Deep OS/NUMA Analysis

### 4.1 Stage 00: `00_fast5_to_pod5` (`13.299 s` Unpinned vs. `7.60 s` 16-Thread)
- **What Happened Inside the OS**:
  - When invoked without `--threads 16`, `pod5 convert fast5` defaulted to a smaller worker pool (`59` total threads vs. `81–82` in Runs 1–3), causing wall-clock runtime to slow down by **`74.9%`** (from `7.60 s` to **`13.30 s`**).
  - Achieved the **highest parallel execution ratio in the pipeline (`80.6%` parallel time**, averaging `2.85` running threads and peaking at `6` simultaneous running threads while `41.64` threads slept on I/O and locks).
- **NUMA & Core Placement Critique**:
  - Remarkably, Linux CFS placed **100% of active CPU execution on Even CPUs (NUMA Node 0)**: top favored cores were `CPU88` (`219` hits), `CPU62` (`211`), `CPU50` (`187`), `CPU0` (`179`), and `CPU56` (`159`). Because `94.18%` of its physical RAM pages (`333,074` peak 4 KB pages = `~1.36 GB` mapped) also resided on Node 0, `pod5` suffered **0 cross-socket bounces** and only **`5.82%` remote NUMA memory access**.

### 4.2 Stage 01: `01_dorado_basecall` (`52.700 s` | `40.87%` Remote NUMA Memory Access!)
- **What Happened Inside the OS**:
  - Spawned **`114` threads** (`96` alive concurrently) across **`72` of the 94 cores**, spending **`60.61%` of wall-clock time in Parallel Execution** (peak `8` running threads, average `1.92` running threads) while an average of **`85.53` threads slept** waiting on GPU (`cuda:1`) streams and ZeroMQ IPC sockets (`6,459,292` voluntary context switches = `99.99%`).
- **Critical Discovery — Severe Cross-Socket NUMA Memory Split (`40.87%` Remote Access)**:
  - Inspection of [`logs/unpinned_baseline/timeseries_scheduler_numa.csv`](../logs/unpinned_baseline/timeseries_scheduler_numa.csv) reveals a textbook **First-Touch NUMA pathology**:
    - While **`88.88%`** of Dorado's CPU execution occurred on **NUMA Node 0** (top cores: `CPU18: 1,052 hits`, `CPU20: 994`, `CPU28: 954`, `CPU8: 901`, `CPU30: 870`), **`11.12%`** of thread execution spilled onto **NUMA Node 1** (`6` cross-socket bounces out of **`201` net core migrations**).
    - Because threads scheduled on Node 1 faulted and initialized large shared ring-buffer and tensor host-staging pages (`93,746` peak pages on Node 1 vs. `161,455` on Node 0), **`38.26%` of Dorado's physical RAM resided permanently on NUMA Node 1**!
    - Consequently, worker threads executing on Socket 0 (`88.9%` of CPU time) had to fetch `38.3%` of their memory across the Intel UPI inter-socket interconnect, resulting in a **`40.87%` estimated remote NUMA memory access penalty**!

### 4.3 Stage 02: `02_nanoplot_qc` (`17.062 s` | `989` Threads | `82.56%` Sequential | `64` Cross-Socket Bounces!)
- **What Happened Inside the OS**:
  - Left unpinned and unflagged, `NanoPlot` spawned **`989` threads** (`135` alive concurrently) that touched **all `94` out of `94` online cores (`100%` server core footprint)**!
- **Critical Discovery 1 — `82.56%` Sequential Bottleneck Despite `989` Threads**:
  - At every `200 ms` sampling tick, an average of **`97.53` threads sat sleeping (`state == 'S'`)** on `futex` locks while an average of only **`1.16` threads actively ran (`state == 'R'`)**!
  - Across the `17.06 s` run, **`82.56%` of wall-clock ticks had $\le 1$ running thread (Sequential Bottleneck)**, and only `17.44%` of ticks achieved $>1$ running thread (peaking at just `4` concurrent running threads).
- **Critical Discovery 2 — `206` Core Migrations & `64` Cross-NUMA Socket Bounces (`31.07%`)**:
  - Because `989` threads repeatedly woke up and blocked on locks (`106,266` voluntary switches), Linux CFS migrated threads across cores **`206` times** (net 200ms transitions), and **`64` of those migrations (`31.07%`) bounced threads directly between Socket 0 and Socket 1**!
  - Furthermore, `25.66%` of NanoPlot's physical RAM (`95,282` peak 4 KB pages) was allocated on Node 1 while `83.20%` of CPU ticks ran on Node 0, generating a **`33.84%` remote NUMA access rate**.

### 4.4 Stage 03: `03_flye_denovo_assembly` (`62.262 s` | `100.0%` Sequential | `17.26%` Forced Preemptions!)
- **What Happened Inside the OS**:
  - **The Unflagged Single-Thread Trap**: Unlike `pod5`, `dorado`, and `NanoPlot` (which auto-spawn dozens or hundreds of threads by default), running `flye` without `--threads` caused it to default to **`--threads 1`**!
  - Consequently, Flye spent **`100.0%` of its `62.262 s` runtime in Sequential Execution (`avg_running_threads = 1.00`, `peak_running_threads = 1`)**, slowing down by `6.36 seconds` (`+11.4%`) compared to the 16-thread run (`55.90 s`).
  - Even with 1 active worker thread at a time, Flye spawned `44` sequential sub-processes/threads across `23` unique cores (`CPU56: 304 hits`, `CPU10: 187`, `CPU58: 102`), migrating cores `9` times.
- **Critical Discovery — Massive Memory Footprint (`2.12 Million` Pages) & `17.26%` Involuntary Preemptions**:
  - `numa_maps` recorded **`2,118,019` peak 4 KB pages on Node 0 + `4,362` pages on Node 1** (`~8.30 GB` mapped physical RAM, `99.83%` local to Node 0).
  - Out of `1,095` total context switches, **`189` (`17.26%`) were involuntary OS preemptions**—the highest forced preemption percentage of any stage in the pipeline!

### 4.5 Stages 04 & 05: `04_minimap2_align` (`0.470 s`) & `05_samtools_sort_index` (`0.497 s`)
- **What Happened Inside the OS**:
  - **`04_minimap2_align` (`0.470 s`)**: Without `-t 16`, `minimap2` defaulted to `3` worker threads (`6` total threads across `6` cores), running `100%` sequentially (`1.0` active thread at each 200ms sample) with **`37.83%` remote NUMA memory access** (`622` pages on Node 1 vs. `1,022` on Node 0) and `8.33%` involuntary preemptions (`1` forced / `11` voluntary).
  - **`05_samtools_sort_index` (`0.497 s`)**: Without `-@ 16`, `samtools sort` and `samtools index` defaulted to single-threaded execution (`2` sequential processes across `CPU58` and `CPU90`), taking **`0.497 s` instead of `0.094 s` (`5.29×` slower than the 16-thread run!)**, confirming how strongly `samtools` benefits from explicit multi-threading.
