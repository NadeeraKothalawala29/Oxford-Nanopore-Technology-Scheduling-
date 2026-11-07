# Research Critique Reports — Oxford Nanopore OS Scheduling Benchmark (`Run 1` – `Run 4`)

This directory contains **research-level systems critique and OS kernel telemetry reports** for all **four pipeline benchmark runs** executed on our Dual-Socket Intel Xeon Gold 6342 (`94` online logical CPUs, `400 GB` RAM, `2` NUMA nodes, `4× NVIDIA A16` GPUs) testbed.

---

## 📂 Index of Pipeline Run Reports

| Run # | Report File | Date & Time (UTC) | Configuration & Profiler | Total Duration | Primary Research Focus |
| :---: | :--- | :---: | :--- | :---: | :--- |
| **Run 1** | [`01_Run1_20261029_210159_Initial_Baseline_Critique.md`](01_Run1_20261029_210159_Initial_Baseline_Critique.md) | `2026-10-29 21:01:59` | `modular_ont` (2 Iterations, `--threads 16`, `10 Hz` `psutil`) | `176.59 s` (`93.3s` + `83.3s`) | Cold vs. Warm Linux VFS page-cache speedup (**`40.1%` faster QC**; `87%` fewer voluntary switches) & profiler calibration |
| **Run 2** | [`02_Run2_20261029_212011_Calibrated_16T_Resource_Critique.md`](02_Run2_20261029_212011_Calibrated_16T_Resource_Critique.md) | `2026-10-29 21:20:11` | `modular_ont` (2 Iterations, `--threads 16`, stateful CPU %) | `163.43 s` (`80.8s` + `82.6s`) | Calibrated multi-core CPU peaks (**`5,457%` in NanoPlot** despite `-t 16`) & **Flye's `8.30 GB` physical RAM wall** |
| **Run 3** | [`03_Run3_20261031_122429_Kernel_CFS_FlameGraph_Critique.md`](03_Run3_20261031_122429_Kernel_CFS_FlameGraph_Critique.md) | `2026-10-31 12:24:29` | Full 6-Stage + GPU `Dorado` (`--threads 16`, **`250 Hz` `/proc/sched`** + FlameGraphs) | `140.68 s` (`135.7s` traced) | Per-thread CFS runqueue wait latency (**`22.53 ms` stall in NanoPlot**), kernel `wchan` analysis, and **Dorado's `6.01M` IPC context switches** |
| **Run 4** | [`04_Run4_20261102_112000_Unpinned_CFS_NUMA_Critique.md`](04_Run4_20261102_112000_Unpinned_CFS_NUMA_Critique.md) | `2026-11-02 11:20:00` | Full 6-Stage **Pure Unpinned Native Defaults** (**`200 ms` `/proc` + `2 s` `numa_maps`**) | `146.29 s` | Unpinned thread explosion (**`989` threads / `82.6%` sequential** in NanoPlot), **`64` cross-socket bounces**, and **`40.9%` remote NUMA memory access** in Dorado |

---

## 📊 Master Cross-Run Comparative Synthesis (Configured 16-Thread vs. Pure Unpinned Defaults)

| Pipeline Stage | Run 1 Duration (Iter 1 / Iter 2) | Run 2 Duration (Iter 1 / Iter 2) | Run 3 Duration (`16T` + `250Hz` CFS) | Run 4 Duration (Unpinned Default) | Peak CPU % (Run 2 / Run 3) | Peak Physical RAM (RSS) | Spawned Threads (`16T` Run 3 vs. Unpinned Run 4) | Core Migrations (`250Hz` Run 3 / `200ms` Run 4) | Primary OS Scheduling Bottleneck Identified |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`00_fast5_to_pod5`** | `7.62s` / `7.62s` | `7.64s` / `7.61s` | **`7.60s`** (`8.66s` wrap) | `13.30s` (`+75%` slower) | `680.9%` / `1,098.9%` | `1,875.6 MB` | `81` vs. `59` | `12` / `6` (`0` cross-NUMA) | File-count worker ceiling (`6` active workers for `6` files); IPC pipe waits |
| **`01_dorado_basecall`** | *Skipped (PATH)* | *Skipped (PATH)* | **`50.82s`** (`cuda:1`) | `52.70s` (`cuda:1`) | Host `1.87×` + GPU | `2,100.0 MB` | `126` vs. `114` | **`2,158`** / **`201`** (`6` cross-NUMA) | **`6.01M–6.46M` ZeroMQ/poll switches** + **`40.9%` remote NUMA RAM access** |
| **`02_nanoplot_qc`** | `28.81s` / `17.25s` | `16.73s` / `16.87s` | **`16.85s`** (`19.21s` wrap) | `17.06s` | `5,457.1%` / **`8,510.4%`** | `2,101.5 MB` | **`1,038`** vs. **`989`** | **`670`** / **`206`** (**`64` cross-NUMA**) | **OpenBLAS/Chrome thread storm (`989–1,038` threads)** $\rightarrow$ **`82.6%` sequential `futex` lock wait** & **`22.5 ms` CFS stall** |
| **`03_flye_denovo_assembly`** | `55.90s` / `56.88s` | `55.91s` / `57.64s` | **`60.03s`** (`61.14s` wrap) | `62.26s` (`1` thread default) | `1,766.9%` / `1,624.5%` | **`8,336.5 MB` (`8.34 GB`)** | `341` vs. `44` | `242` / `9` | **`8.34 GB` physical RAM wall** + **`74.7%`–`100%` single-thread serialization** + **`17.3%` forced preemptions** |
| **`04_minimap2_align`** | `0.51s` / `0.50s` | `0.42s` / `0.42s` | **`0.36s`** (`0.52s` wrap) | `0.47s` (`3` threads default) | `252.0%` / `276.4%` | `43.8 MB` | `56` vs. `6` | `0` / `0` | **`37.8%` remote NUMA page placement** on short burst runs |
| **`05_samtools_sort_index`** | `0.50s` / `0.51s` | `0.11s` / `0.11s` | **`0.094s`** (`0.31s` wrap) | `0.50s` (`5.3×` slower default) | `546%` effective | `74.1 MB` | `37` vs. `2` | `1` / `0` | Defaults to `1` thread (`0.50s`) unless `-@` is passed (`0.094s`, `5.46×` speedup) |

---

## 🎯 Key Architectural Takeaways for Portable Handheld Edge Devices

1. **CLI Thread Flags (`-t`) Do Not Prevent OS Thread Storms**:
   - In **Run 2** and **Run 3**, passing `-t 16` to `NanoPlot` failed to stop `OpenBLAS` and headless `Chromium` (`kaleido`) from querying total online host CPUs (`94`) and spawning **`989–1,038` threads**, spiking CPU to **`8,510.4%`**, inducing **`22.53 ms` CFS runqueue stalls**, and wasting **`82.6%` of wall-clock time in sequential lock contention**.
   - **Handheld Rule**: Edge deployments must enforce strict OS-level **`cgroups v2` (`cpu.max`) containers**, **`taskset` CPU affinity masks**, and math-library environment caps (`OPENBLAS_NUM_THREADS=4`, `OMP_NUM_THREADS=4`).
2. **Inconsistent Native Threading Defaults Across Stages**:
   - Left unflagged in **Run 4**, `NanoPlot` (`989` threads) and `Dorado` (`114` threads) over-subscribed the CPU, whereas `Flye` and `Samtools` defaulted to **1 single thread (`100%` sequential)**, slowing `Samtools` by **`5.29×`** (`0.497 s` vs. `0.094 s`) and `POD5` by **`1.75×`** (`13.30 s` vs. `7.60 s`).
   - **Handheld Rule**: Every pipeline stage must be explicitly configured to match the physical core count of the target edge SoC.
3. **Unpinned CFS Thread Bouncing & NUMA / Cluster Locality Penalties**:
   - Unpinned execution caused **`2,158` core migrations in Dorado (Run 3)** and **`670` migrations in NanoPlot (Run 3)** (including **`64` cross-socket bounces in Run 4**), alongside a **`40.87%` cross-socket remote RAM access penalty in Dorado**.
   - **Handheld Rule**: On heterogeneous edge SoCs (ARM `big.LITTLE` / Jetson Orin shared CPU–GPU LPDDR5), threads must be pinned to a single core cluster (`sched_setaffinity`) with local memory binding (`numactl`) to prevent L2 cache invalidation and memory-bus saturation.
4. **The `8.34 GB` Memory Wall Splits Streaming Alignment from De-Novo Assembly**:
   - Across all 4 runs, **reference-based streaming stages (`POD5` $\rightarrow$ `Dorado` $\rightarrow$ `Minimap2` $\rightarrow$ `Samtools`) peaked at $\le 2.10\text{ GB}$ RAM**, proving they can execute comfortably on a **4–8 GB handheld edge device**.
   - Conversely, **`Flye` de-novo assembly required `8.24–8.34 GB` physical RSS** even on a `13.04 Mb` dataset, establishing a hard **`16 GB` RAM minimum** for on-device de-novo assembly.
