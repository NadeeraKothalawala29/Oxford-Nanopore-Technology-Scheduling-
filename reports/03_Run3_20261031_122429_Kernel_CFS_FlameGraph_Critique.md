# Pipeline Run 3 — Research Critique & Kernel CFS Analysis (`sched_profile_20261031_122429`)

## 1. Run Metadata & Experimental Context

| Metadata Field | Value |
| :--- | :--- |
| **Pipeline Executed** | Complete 6-Stage Modular Oxford Nanopore Pipeline (`modular_ont` + Standalone GPU `Dorado` Basecalling) |
| **Run Tag / Identifier** | `sched_profile_20261031_122429` (Experiment Phase 2A — 250 Hz Kernel CFS Latency & Wait-Channel Profiling) |
| **Execution Date & Time** | October 31, 2026 — `12:24:29` to `12:26:50` UTC |
| **Total Wall-Clock Duration** | **`140.68 seconds` total** (`89.854 s` across 5 CPU pipeline stages + `50.819 s` GPU Dorado basecalling on `cuda:1` = `135.744 s` pure traced execution) |
| **Configured Thread & GPU Budget** | `--threads 16` (`-t 16` / `-@ 16`) + NVIDIA A16 GPU (`cuda:1`, model `dna_r9.4.1_e8_fast@v3.4`) |
| **Sampling Granularity** | **`250 Hz` (`4 ms` interval)** per-thread kernel `/proc/<pid>/task/<tid>/{sched,schedstat,wchan,stat}` tracer + `10 Hz` macro resource monitor |
| **Primary Telemetry & Visual Files** | [`logs/summary_sched_profile_20261031_122429.csv`](../logs/summary_sched_profile_20261031_122429.csv), [`logs/timeseries_sched_profile_20261031_122429.csv`](../logs/timeseries_sched_profile_20261031_122429.csv), [`logs/sched_profile_iter1_*_latency_report.txt`](../logs/), [`logs/sched_profile_iter1_*_sched_profile.html`](../logs/) |

---

## 2. What Was Measured in Run 3

Because container security (`perf_event_paranoid = 4`) restricts unprivileged hardware PMU tracepoints, we engineered a `250 Hz` (`4 ms`) kernel scheduler profiler wrapped via [`scripts/trace_scheduler.sh`](../scripts/trace_scheduler.sh) and integrated Brendan Gregg's `FlameGraph` toolkit (`stackcollapse-perf.pl` + `flamegraph.pl`). Across all **6 pipeline stages** (including GPU basecalling via [`scripts/run_dorado_stage.sh`](../scripts/run_dorado_stage.sh)), Run 3 measured:
1. **Per-Thread On-CPU Runtime (`Runtime ms`)** from kernel CFS `se.sum_exec_runtime`.
2. **CFS Runqueue Wait Latency (`Avg wait ms`, `Max wait ms`, `Max wait at s`)** — Time a runnable thread spent waiting in a CPU runqueue before being scheduled onto a core, derived from Linux PELT (`se.avg.runnable_sum` vs. `se.avg.util_sum`) and `schedstat`.
3. **Thread-Level Voluntary vs. Involuntary Context Switches (`Vol / Invol`)** — Exact per-TID switch breakdown across all **`1,679` threads** spawned across the 6 stages.
4. **Per-Thread CPU Core Migrations (`Migrations`)** — Exact count of `se.nr_migrations` when the Linux CFS load balancer moved a thread between logical CPUs (`0–93`).
5. **Kernel Wait Channels (`Last Wchan` & Interactive HTML FlameGraphs)** — Identifying the exact Linux kernel function where sleeping threads block (`futex_wait_queue_me`, `do_epoll_wait`, `do_sys_poll`, `hrtimer_nanosleep`, vs. `userspace_on_cpu`).

---

## 3. Master Telemetry Summary Table (Run 3: All 6 Traced Stages)

| Stage | Traced Wall Time (s) | Wrapper Duration (s) | Peak CPU (%) | Peak RSS (MB) | Traced Threads (TIDs) | Cumulative CPU Runtime (ms) | Effective Parallelism ($\text{CPU}/\text{Wall}$) | Context Switches (`Vol / Invol`) | Core Migrations (`se.nr_migrations`) | Max CFS Wait Latency | Dominant Kernel Wait Channel (`wchan`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`00_fast5_to_pod5`** | `7.595 s` | `8.663 s` | `1,098.9%` | `1,875.57 MB` | `81` | `38,942.7 ms` | **`5.13×`** | `19,810 / 102` | `12` | `0.7915 ms` | `userspace_on_cpu`, `futex_wait_queue_me` |
| **`01_dorado_basecall`** | `50.819 s` | `50.819 s` | GPU (`cuda:1`) | `~2,100 MB` | `126` | `94,920.4 ms` | **`1.87×`** (Host) | **`6,007,063 / 283`** | **`2,158`** | `9.9351 ms` | `do_sys_poll`, `do_epoll_wait`, `futex_wait_queue_me` |
| **`02_nanoplot_qc`** | `16.852 s` | `19.213 s` | **`8,510.4%`** | `2,101.49 MB` | **`1,038`** | `29,602.4 ms` | **`1.76×`** | `139,975 / 782` | **`670`** | **`22.5296 ms`** | `futex_wait_queue_me`, `userspace_on_cpu` |
| **`03_flye_denovo_assembly`** | `60.026 s` | `61.142 s` | `1,624.5%` | **`8,336.48 MB`** | `341` | `73,877.2 ms` | **`1.23×`** | `37,134 / 282` | `242` | `0.0890 ms` | `userspace_on_cpu` (`74.7%` on 1 master thread) |
| **`04_minimap2_align`** | `0.358 s` | `0.523 s` | `276.4%` | `43.75 MB` | `56` | `399.5 ms` | **`1.12×`** | `150 / 0` | `0` | `0.0000 ms` | `userspace_on_cpu`, `futex_wait_queue_me` |
| **`05_samtools_sort_index`** | `0.094 s` | `0.313 s` | `<1s burst` | `74.05 MB` | `37` | `513.5 ms` | **`5.46×`** | `3,916 / 1` | `1` | `0.0078 ms` | `futex_wait_queue_me`, `hrtimer_nanosleep` |

---

## 4. Stage-by-Stage Research Critique & Kernel Wait-Channel Analysis

### 4.1 Stage 00: `00_fast5_to_pod5` (`7.595 s` wall time | `38,942.7 ms` CPU time)
- **Latency Report & FlameGraph**: [`logs/sched_profile_iter1_00_fast5_to_pod5_latency_report.txt`](../logs/sched_profile_iter1_00_fast5_to_pod5_latency_report.txt) | [`sched_profile.html`](../logs/sched_profile_iter1_00_fast5_to_pod5_sched_profile.html)
- **What Happened Inside the Kernel**:
  - Out of **`81` spawned threads**, almost all actual CPU work (`36,230 ms` out of `38,942.7 ms`, or **`93.0%`**) was performed by exactly **6 Python decompression/conversion worker processes** (`python3:101`, `python3:98`, `python3:99`, `python3:96`, `python3:100`, `python3:97`), each executing on-CPU for `4,631 ms` to `6,471 ms` (`~1,740` voluntary switches each) while the master `pod5:77` writer ran for `1,494.7 ms` (`3,124` voluntary switches, max runqueue wait `0.7915 ms` at `7.59 s`).
  - Why did `--threads 16` only activate 6 heavy workers? Because the dataset contains **6 `.fast5` input files**, and `pod5 convert` assigns one worker process per input file!
  - Meanwhile, the remaining `~74` threads (`jemalloc_bg_thd` memory allocator background threads and idle worker pool threads) spent `< 205 ms` on-CPU and blocked continuously in `futex_wait_queue_me`.

### 4.2 Stage 01: `01_dorado_basecall` (`50.819 s` wall time | `94,920.4 ms` CPU time | GPU `cuda:1`)
- **Latency Report & FlameGraph**: [`logs/sched_profile_iter1_01_dorado_basecall_latency_report.txt`](../logs/sched_profile_iter1_01_dorado_basecall_latency_report.txt) | [`sched_profile.html`](../logs/sched_profile_iter1_01_dorado_basecall_sched_profile.html)
- **What Happened Inside the Kernel**:
  - Basecalled **`134,857,784` raw ionic current samples** across `22,890` reads on NVIDIA A16 GPU `cuda:1` (`3.09 million samples/sec`).
  - Spawned **`126` threads** across the `dorado_basecall_server` and `ont_basecall_client` process tree, accumulating `94.92 s` of host CPU time (**`1.87×` average host CPU concurrency**).
- **Critical Discovery — The 6.01 Million Context-Switch & 2,158 Migration Storm**:
  - Dorado generated an astonishing **`6,007,346` context switches** (`6,007,063` voluntary / `283` involuntary = **`118,210` switches/sec**) and **`2,158` CPU core migrations**!
  - **Exact Thread Culprits Identified in the Latency Report**:
    1. `basecall_server:33362` (`11,714.4 ms` CPU): **`1,403,853` switches** (`81` migrations), blocking in `do_sys_poll`.
    2. `ZMQbg/1:333591` & `ZMQbg/1:333635` (ZeroMQ IPC background threads, `9,492.8 ms` & `9,847.0 ms` CPU): **`1,408,529` and `1,401,328` switches** (`95` and `113` migrations), blocking in `do_epoll_wait`.
    3. `client_worker:333633` (`6,486.3 ms` CPU): **`709,517` switches** (`50` migrations), blocking in `hrtimer_nanosleep`.
    4. `socket_polling:333627` & `333628` (`4,172.8 ms` & `3,542.6 ms` CPU): **`350,917` switches each** (`41` and **`247` migrations**!), blocking in `do_sys_poll`.
    5. `pipeline_ctrl:333588` (`20,169.2 ms` CPU): Suffered **`130` involuntary preemptions**, **`103` core migrations**, and a **`9.9351 ms` maximum CFS runqueue wait spike**!
  - **Architectural Critique**: Decoupling Dorado into a client/server IPC architecture over ZeroMQ sockets (`do_epoll_wait` / `do_sys_poll`) causes millions of microsecond sleep/wakeup transitions. Every time a ZeroMQ or socket-polling thread wakes up unpinned, Linux CFS `select_task_rq_fair()` searches for an idle core across the 94-CPU server, triggering **`2,158` core migrations** and severe cross-socket cache thrashing.

### 4.3 Stage 02: `02_nanoplot_qc` (`16.852 s` wall time | `29,602.4 ms` CPU time)
- **Latency Report & FlameGraph**: [`logs/sched_profile_iter1_02_nanoplot_qc_latency_report.txt`](../logs/sched_profile_iter1_02_nanoplot_qc_latency_report.txt) | [`sched_profile.html`](../logs/sched_profile_iter1_02_nanoplot_qc_sched_profile.html)
- **What Happened Inside the Kernel**:
  - Peak CPU surged to **`8,510.4%`** (~85 logical cores simultaneously), and our 250 Hz tracer captured **`1,038` total spawned threads (TIDs)** across the stage's lifetime!
  - **The Paradox of `8,510%` Peak CPU vs. `1.76×` Average Parallelism**:
    - Despite spawning `1,038` threads and briefly hitting `8,510.4%` CPU, cumulative CPU time across all `1,038` threads was only **`29,602.4 ms`** over **`16.852 s`** of wall-clock time—an effective average parallelism of just **`1.76` active cores**!
    - **Why?** Look at the top tasks in the latency report: NanoPlot launches multiple headless **Chromium (`chrome`)** browser instances via `kaleido` (`chrome:1083`, `chrome:939`, `chrome:1229`, `chrome:658`, `chrome:380`, `chrome:798`, `chrome:520`, running `1.05 s–1.67 s` each) alongside `OpenBLAS` worker pools. Each `chrome` instance and math library spawns dozens of `ThreadPoolForeg` and `futex`-waiting worker threads (`139,975` voluntary switches, `670` core migrations).
    - This thread stampede starved the main Python thread **`NanoPlot:179`** (`1,504.5 ms` runtime), which suffered **`540` involuntary preemptions** (out of `782` total across all 1,038 threads = **`69.1%` of all forced preemptions!**) and experienced the **worst CFS runqueue scheduling stall in the entire pipeline: `22.5296 ms` max wait latency**!

### 4.4 Stage 03: `03_flye_denovo_assembly` (`60.026 s` wall time | `73,877.2 ms` CPU time)
- **Latency Report & FlameGraph**: [`logs/sched_profile_iter1_03_flye_denovo_assembly_latency_report.txt`](../logs/sched_profile_iter1_03_flye_denovo_assembly_latency_report.txt) | [`sched_profile.html`](../logs/sched_profile_iter1_03_flye_denovo_assembly_sched_profile.html)
- **What Happened Inside the Kernel**:
  - Peak RSS hit **`8,336.48 MB` (`8.34 GB`)** and Peak CPU hit **`1,624.5%`**, spawning **`341` total threads** across Flye's sequential sub-programs (`flye-modules`, `flye-minimap2`, `flye-samtools`) with `37,416` switches and `242` migrations.
- **Critical Discovery — Severe Amdahl's Law Serialization (`1.23×` Effective Parallelism)**:
  - Even though `--threads 16` was passed and Peak CPU briefly touched `1,624.5%` (during `flye-modules:1417..1432` where 16 worker threads each executed for `~437 ms` in parallel), look at the #1 thread in the latency report:
    - **`flye-modules:1304`** executed on-CPU for **`55,218.620 ms` (`55.22 seconds`)** out of the `60.026 s` wall-clock stage duration—accounting for **`74.74%` of all CPU time across all 341 threads**!
    - Because `flye-modules:1304` ran a single-threaded C++ repeat-graph construction and memory allocation loop for `55.22 s` straight, it suffered **`195` involuntary preemptions** (`69.1%` of the stage's `282` forced preemptions) and **`12` core migrations**, yielding an overall effective stage parallelism of only **`1.23×`** (`73.88 s / 60.03 s`)!

### 4.5 Stages 04 & 05: `04_minimap2_align` (`0.358 s`) & `05_samtools_sort_index` (`0.094 s`)
- **Latency Reports & FlameGraphs**: [`04_minimap2_align_latency_report.txt`](../logs/sched_profile_iter1_04_minimap2_align_latency_report.txt), [`05_samtools_sort_index_latency_report.txt`](../logs/sched_profile_iter1_05_samtools_sort_index_latency_report.txt)
- **What Our 250 Hz (`4 ms`) Profiler Revealed in Sub-Second Stages**:
  - **`04_minimap2_align` (`358 ms` wall time, `43.75 MB` RSS)**: Spawned `56` threads across 3 short invocations (`399.45 ms` total CPU time, `150` voluntary switches, **`0` involuntary preemptions**, **`0` migrations**).
  - **`05_samtools_sort_index` (`94 ms` wall time, `74.05 MB` RSS)**: Whereas 10 Hz polling in Runs 1 & 2 missed `samtools`, our `4 ms` profiler captured all **`37` threads** (`16` sort threads + `16` index threads + master threads), logging **`513.47 ms` of CPU runtime inside just `94 ms` of wall-clock time**—achieving the **highest parallel efficiency in the pipeline (`5.46×` effective parallelism)** with `3,916` voluntary `futex` switches, `1` involuntary switch, and `1` migration!
