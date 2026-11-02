#!/usr/bin/env python3
"""
Unprivileged /proc Scheduler & NUMA Telemetry Profiler for Nanopore Pipelines.
Runs each Nanopore bioinformatics pipeline stage in its pure, default unpinned state
(no taskset, no numactl, no forced thread counts) and samples /proc/<pid>/task/<tid>/
and /proc/<pid>/numa_maps every 200ms (0.2s) to capture:
  1. Cores & Thread Assignment (per-core hit histogram 0-93, spawned threads, active cores)
  2. Sequential vs. Parallel Execution (state == 'R' vs 'S'/'D', concurrency degree)
  3. CPU Core Migrations & Cross-NUMA Socket Bounces (even=Node0 vs odd=Node1)
  4. Voluntary vs. Involuntary Preemptions (/proc/<pid>/task/<tid>/status)
  5. NUMA Page Allocation (N0 vs N1 page counts from /proc/<pid>/numa_maps)
  6. Core Pinning & NUMA Affiliation (Cpus_allowed_list, Mems_allowed_list, exec vs mem locality)
"""
import os
import re
import sys
import csv
import glob
import json
import time
import argparse
import threading
import subprocess
from datetime import datetime
import psutil

RE_N0 = re.compile(r"\bN0=(\d+)")
RE_N1 = re.compile(r"\bN1=(\d+)")
NUM_CORES = 96  # 0-93 online, 94-95 offline on dual Xeon Gold 6342


class UnpinnedStageProfiler:
    def __init__(self, root_pid, stage_name, ts_writer, ts_file, interval=0.2):
        self.root_pid = root_pid
        self.stage_name = stage_name
        self.ts_writer = ts_writer
        self.ts_file = ts_file
        self.interval = interval
        self.stop_event = threading.Event()

        # 1. Cores & Thread Assignment
        self.seen_tids = set()
        self.active_cores_seen = set()
        self.core_hits = {c: 0 for c in range(NUM_CORES)}
        self.core_running_hits = {c: 0 for c in range(NUM_CORES)}
        self.max_concurrent_threads_alive = 0

        # 2. Sequential vs Parallel Execution
        self.total_ticks = 0
        self.sequential_ticks = 0
        self.parallel_ticks = 0
        self.running_counts_per_tick = []
        self.sleeping_counts_per_tick = []
        self.disk_wait_counts_per_tick = []
        self.peak_running_concurrency = 0

        # 3. CPU Core Migrations & Cross-NUMA Bounces
        self.last_cpu = {}
        self.total_core_migrations = 0
        self.cross_numa_socket_bounces = 0

        # 4. Voluntary vs Involuntary Preemptions (tracked per TID so exiting threads are retained)
        self.vol_switches_by_tid = {}
        self.invol_switches_by_tid = {}

        # 5. NUMA Page Allocation (Node 0 vs Node 1)
        self.latest_n0_pages = 0
        self.latest_n1_pages = 0
        self.peak_n0_pages = 0
        self.peak_n1_pages = 0
        self.n0_pages_samples = []
        self.n1_pages_samples = []

        # 6. Core Pinning & NUMA Affiliation
        self.cpus_allowed_list = "0-93"
        self.mems_allowed_list = "0-1"
        self.node0_exec_samples = 0
        self.node1_exec_samples = 0
        self.node0_running_samples = 0
        self.node1_running_samples = 0

        # Timeline series for HTML dashboard
        self.timeline = []

    def _get_process_tree_pids(self):
        pids = [self.root_pid]
        try:
            parent = psutil.Process(self.root_pid)
            for child in parent.children(recursive=True):
                pids.append(child.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return pids

    def _read_tid_stat(self, pid, tid):
        """Parse /proc/<pid>/task/<tid>/stat for state (field 3) and task_cpu/psr (field 39)."""
        stat_path = f"/proc/{pid}/task/{tid}/stat"
        try:
            with open(stat_path, "r") as f:
                data = f.read()
            rpar = data.rfind(")")
            if rpar == -1:
                return None
            fields = data[rpar + 2:].split()
            state = fields[0]
            # Field 3 is fields[0], so Field 39 (processor) is fields[36]
            cpu_id = int(fields[36]) if len(fields) > 36 else 0
            utime = int(fields[11]) if len(fields) > 12 else 0
            stime = int(fields[12]) if len(fields) > 12 else 0
            return state, cpu_id, utime + stime
        except Exception:
            return None

    def _read_tid_status(self, pid, tid):
        """Parse /proc/<pid>/task/<tid>/status for context switches and affinity masks."""
        status_path = f"/proc/{pid}/task/{tid}/status"
        vol = None
        invol = None
        cpus_allowed = None
        mems_allowed = None
        try:
            with open(status_path, "r") as f:
                for line in f:
                    if line.startswith("voluntary_ctxt_switches:"):
                        vol = int(line.split(":", 1)[1].strip())
                    elif line.startswith("nonvoluntary_ctxt_switches:"):
                        invol = int(line.split(":", 1)[1].strip())
                    elif line.startswith("Cpus_allowed_list:"):
                        cpus_allowed = line.split(":", 1)[1].strip()
                    elif line.startswith("Mems_allowed_list:"):
                        mems_allowed = line.split(":", 1)[1].strip()
        except Exception:
            pass
        return vol, invol, cpus_allowed, mems_allowed

    def _sample_numa_maps(self, pids):
        """Parse /proc/<pid>/numa_maps across active PIDs in the stage."""
        total_n0 = 0
        total_n1 = 0
        for pid in pids:
            numa_path = f"/proc/{pid}/numa_maps"
            try:
                with open(numa_path, "r") as f:
                    content = f.read()
                for m0 in RE_N0.finditer(content):
                    total_n0 += int(m0.group(1))
                for m1 in RE_N1.finditer(content):
                    total_n1 += int(m1.group(1))
            except Exception:
                continue
        if total_n0 > 0 or total_n1 > 0:
            self.latest_n0_pages = total_n0
            self.latest_n1_pages = total_n1
            self.peak_n0_pages = max(self.peak_n0_pages, total_n0)
            self.peak_n1_pages = max(self.peak_n1_pages, total_n1)
            self.n0_pages_samples.append(total_n0)
            self.n1_pages_samples.append(total_n1)

    def monitor(self):
        start_wall = time.time()
        tick_idx = 0
        # Short initial delay (30ms) so fast stages (<200ms) still get sampled at least once
        time.sleep(0.03)

        while not self.stop_event.is_set():
            tick_start = time.time()
            elapsed = round(tick_start - start_wall, 3)

            try:
                root_p = psutil.Process(self.root_pid)
                if not root_p.is_running() or root_p.status() == psutil.STATUS_ZOMBIE:
                    break
            except psutil.NoSuchProcess:
                break

            pids = self._get_process_tree_pids()
            # Filter out top-level /bin/sh wrapper if real stage children exist
            target_pids = pids[1:] if len(pids) > 1 else pids

            running_now = 0
            sleeping_now = 0
            disk_wait_now = 0
            alive_threads_now = 0
            tick_migrations = 0
            tick_numa_bounces = 0
            tick_n0_threads = 0
            tick_n1_threads = 0
            tick_active_cores = set()

            for pid in target_pids:
                task_dir = f"/proc/{pid}/task"
                try:
                    tids = [int(t) for t in os.listdir(task_dir) if t.isdigit()]
                except Exception:
                    continue

                for tid in tids:
                    stat_res = self._read_tid_stat(pid, tid)
                    if stat_res is None:
                        continue
                    state, cpu_id, cpu_ticks = stat_res

                    alive_threads_now += 1
                    self.seen_tids.add(tid)
                    if 0 <= cpu_id < NUM_CORES:
                        self.core_hits[cpu_id] += 1
                        self.active_cores_seen.add(cpu_id)
                        tick_active_cores.add(cpu_id)

                    if cpu_id % 2 == 0:
                        self.node0_exec_samples += 1
                        tick_n0_threads += 1
                    else:
                        self.node1_exec_samples += 1
                        tick_n1_threads += 1

                    if state == "R":
                        running_now += 1
                        if 0 <= cpu_id < NUM_CORES:
                            self.core_running_hits[cpu_id] += 1
                        if cpu_id % 2 == 0:
                            self.node0_running_samples += 1
                        else:
                            self.node1_running_samples += 1
                    elif state == "D":
                        disk_wait_now += 1
                        sleeping_now += 1
                    else:
                        sleeping_now += 1

                    # Check core migration & cross-NUMA socket bounce
                    if tid in self.last_cpu:
                        prev_cpu = self.last_cpu[tid]
                        if cpu_id != prev_cpu:
                            self.total_core_migrations += 1
                            tick_migrations += 1
                            if (cpu_id % 2) != (prev_cpu % 2):
                                self.cross_numa_socket_bounces += 1
                                tick_numa_bounces += 1
                    self.last_cpu[tid] = cpu_id

                    # Read context switches & affinity
                    vol, invol, cpus_allow, mems_allow = self._read_tid_status(pid, tid)
                    if vol is not None:
                        self.vol_switches_by_tid[tid] = vol
                    if invol is not None:
                        self.invol_switches_by_tid[tid] = invol
                    if cpus_allow:
                        self.cpus_allowed_list = cpus_allow
                    if mems_allow:
                        self.mems_allowed_list = mems_allow

            # Sample /proc/<pid>/numa_maps on first tick and every 10 ticks (2.0s)
            if tick_idx % 10 == 0:
                self._sample_numa_maps(target_pids)

            if alive_threads_now > 0:
                self.total_ticks += 1
                self.max_concurrent_threads_alive = max(self.max_concurrent_threads_alive, alive_threads_now)
                self.peak_running_concurrency = max(self.peak_running_concurrency, running_now)
                self.running_counts_per_tick.append(running_now)
                self.sleeping_counts_per_tick.append(sleeping_now)
                self.disk_wait_counts_per_tick.append(disk_wait_now)

                exec_mode = "PARALLEL" if running_now > 1 else "SEQUENTIAL"
                if running_now > 1:
                    self.parallel_ticks += 1
                else:
                    self.sequential_ticks += 1

                tot_vol = sum(self.vol_switches_by_tid.values())
                tot_invol = sum(self.invol_switches_by_tid.values())
                n0_p = self.latest_n0_pages
                n1_p = self.latest_n1_pages
                tot_p = max(1, n0_p + n1_p)
                n0_mem_pct = round(100.0 * n0_p / tot_p, 2)
                n1_mem_pct = round(100.0 * n1_p / tot_p, 2)

                tot_t = max(1, tick_n0_threads + tick_n1_threads)
                n0_cpu_pct = round(100.0 * tick_n0_threads / tot_t, 2)
                n1_cpu_pct = round(100.0 * tick_n1_threads / tot_t, 2)

                row = [
                    datetime.now().isoformat(),
                    self.stage_name,
                    elapsed,
                    alive_threads_now,
                    len(self.seen_tids),
                    running_now,
                    sleeping_now,
                    disk_wait_now,
                    exec_mode,
                    len(tick_active_cores),
                    tick_migrations,
                    self.total_core_migrations,
                    tick_numa_bounces,
                    self.cross_numa_socket_bounces,
                    tot_vol,
                    tot_invol,
                    n0_p,
                    n1_p,
                    n0_mem_pct,
                    n1_mem_pct,
                    n0_cpu_pct,
                    n1_cpu_pct,
                    self.cpus_allowed_list,
                    self.mems_allowed_list,
                ]
                self.ts_writer.writerow(row)
                self.ts_file.flush()

                self.timeline.append({
                    "elapsed_s": elapsed,
                    "running": running_now,
                    "sleeping": sleeping_now,
                    "alive": alive_threads_now,
                    "migrations_cum": self.total_core_migrations,
                    "bounces_cum": self.cross_numa_socket_bounces,
                    "n0_pages": n0_p,
                    "n1_pages": n1_p,
                })

            tick_idx += 1
            sleep_rem = self.interval - (time.time() - tick_start)
            if sleep_rem > 0:
                self.stop_event.wait(sleep_rem)

    def summarize(self, duration_sec, return_code):
        total_t = max(1, self.total_ticks)
        seq_pct = round(100.0 * self.sequential_ticks / total_t, 2)
        par_pct = round(100.0 * self.parallel_ticks / total_t, 2)
        avg_running = round(sum(self.running_counts_per_tick) / total_t, 2) if self.running_counts_per_tick else 0.0
        avg_sleeping = round(sum(self.sleeping_counts_per_tick) / total_t, 2) if self.sleeping_counts_per_tick else 0.0

        tot_vol = sum(self.vol_switches_by_tid.values())
        tot_invol = sum(self.invol_switches_by_tid.values())
        tot_sw = max(1, tot_vol + tot_invol)
        vol_pct = round(100.0 * tot_vol / tot_sw, 2)
        invol_pct = round(100.0 * tot_invol / tot_sw, 2)

        avg_n0_pages = int(round(sum(self.n0_pages_samples) / len(self.n0_pages_samples))) if self.n0_pages_samples else self.peak_n0_pages
        avg_n1_pages = int(round(sum(self.n1_pages_samples) / len(self.n1_pages_samples))) if self.n1_pages_samples else self.peak_n1_pages
        tot_pages = max(1, avg_n0_pages + avg_n1_pages)
        n0_mem_pct = round(100.0 * avg_n0_pages / tot_pages, 2)
        n1_mem_pct = round(100.0 * avg_n1_pages / tot_pages, 2)

        tot_exec = max(1, self.node0_exec_samples + self.node1_exec_samples)
        n0_exec_pct = round(100.0 * self.node0_exec_samples / tot_exec, 2)
        n1_exec_pct = round(100.0 * self.node1_exec_samples / tot_exec, 2)

        # Quantify NUMA Locality vs Remote Memory Mismatch:
        # Expected local memory access probability if CPU execution on Node i accesses Node i/j pages proportionally:
        # P(local) = (exec_N0 * mem_N0) + (exec_N1 * mem_N1)
        # P(remote) = (exec_N0 * mem_N1) + (exec_N1 * mem_N0)
        p_local = ((n0_exec_pct / 100.0) * (n0_mem_pct / 100.0) + (n1_exec_pct / 100.0) * (n1_mem_pct / 100.0)) * 100.0
        p_remote = 100.0 - p_local

        top_cores = sorted(self.core_hits.items(), key=lambda x: x[1], reverse=True)[:10]
        top_cores_str = "; ".join(f"CPU{c}:{cnt}" for c, cnt in top_cores if cnt > 0)

        return {
            "stage": self.stage_name,
            "status": "SUCCESS" if return_code == 0 else f"FAILED({return_code})",
            "duration_sec": round(duration_sec, 3),
            "samples_collected": self.total_ticks,
            "total_spawned_threads": len(self.seen_tids),
            "max_concurrent_threads_alive": self.max_concurrent_threads_alive,
            "unique_active_cores_count": len(self.active_cores_seen),
            "top_favored_cores": top_cores_str,
            "sequential_time_pct": seq_pct,
            "parallel_time_pct": par_pct,
            "avg_running_threads": avg_running,
            "peak_running_threads": self.peak_running_concurrency,
            "avg_sleeping_threads": avg_sleeping,
            "total_core_migrations": self.total_core_migrations,
            "cross_numa_socket_bounces": self.cross_numa_socket_bounces,
            "numa_bounce_ratio_pct": round(100.0 * self.cross_numa_socket_bounces / max(1, self.total_core_migrations), 2),
            "voluntary_ctxt_switches": tot_vol,
            "nonvoluntary_ctxt_switches": tot_invol,
            "voluntary_switch_pct": vol_pct,
            "involuntary_preemption_pct": invol_pct,
            "numa_node0_pages_avg": avg_n0_pages,
            "numa_node1_pages_avg": avg_n1_pages,
            "numa_node0_pages_peak": self.peak_n0_pages,
            "numa_node1_pages_peak": self.peak_n1_pages,
            "numa_node0_mem_pct": n0_mem_pct,
            "numa_node1_mem_pct": n1_mem_pct,
            "numa_node0_cpu_exec_pct": n0_exec_pct,
            "numa_node1_cpu_exec_pct": n1_exec_pct,
            "estimated_numa_local_access_pct": round(p_local, 2),
            "estimated_numa_remote_access_pct": round(p_remote, 2),
            "cpus_allowed_list": self.cpus_allowed_list,
            "mems_allowed_list": self.mems_allowed_list,
            "core_hits": self.core_hits,
            "core_running_hits": self.core_running_hits,
            "timeline": self.timeline,
        }


def generate_html_dashboard(summaries, out_html_path):
    stages = [s["stage"] for s in summaries]
    seq_pcts = [s["sequential_time_pct"] for s in summaries]
    par_pcts = [s["parallel_time_pct"] for s in summaries]
    avg_run = [s["avg_running_threads"] for s in summaries]
    peak_run = [s["peak_running_threads"] for s in summaries]
    spawned = [s["total_spawned_threads"] for s in summaries]

    n0_exec = [s["numa_node0_cpu_exec_pct"] for s in summaries]
    n1_exec = [s["numa_node1_cpu_exec_pct"] for s in summaries]
    n0_mem = [s["numa_node0_mem_pct"] for s in summaries]
    n1_mem = [s["numa_node1_mem_pct"] for s in summaries]
    remote_est = [s["estimated_numa_remote_access_pct"] for s in summaries]

    migrations = [s["total_core_migrations"] for s in summaries]
    bounces = [s["cross_numa_socket_bounces"] for s in summaries]

    vol_sw = [s["voluntary_ctxt_switches"] for s in summaries]
    invol_sw = [s["nonvoluntary_ctxt_switches"] for s in summaries]

    # Build per-core heatmap matrix (stages x 94 online cores)
    core_labels = [f"C{c}" for c in range(94)]
    heatmap_z = [[s["core_hits"].get(c, 0) for c in range(94)] for s in summaries]

    # Build table rows
    table_rows_html = ""
    for s in summaries:
        table_rows_html += f"""
        <tr>
            <td><strong>{s['stage']}</strong></td>
            <td><span class="badge-ok">{s['status']}</span></td>
            <td>{s['duration_sec']:.2f}s</td>
            <td>{s['total_spawned_threads']} ({s['unique_active_cores_count']} cores)</td>
            <td>{s['sequential_time_pct']:.1f}% / <strong>{s['parallel_time_pct']:.1f}%</strong></td>
            <td>{s['avg_running_threads']:.2f} (peak {s['peak_running_threads']})</td>
            <td>{s['total_core_migrations']:,}</td>
            <td><strong>{s['cross_numa_socket_bounces']:,}</strong> ({s['numa_bounce_ratio_pct']:.1f}%)</td>
            <td>{s['voluntary_ctxt_switches']:,} / {s['nonvoluntary_ctxt_switches']:,}</td>
            <td>{s['numa_node0_mem_pct']:.1f}% / {s['numa_node1_mem_pct']:.1f}%</td>
            <td>{s['numa_node0_cpu_exec_pct']:.1f}% / {s['numa_node1_cpu_exec_pct']:.1f}%</td>
            <td><strong>{s['estimated_numa_remote_access_pct']:.1f}%</strong></td>
            <td><code>{s['cpus_allowed_list']}</code> | <code>{s['mems_allowed_list']}</code></td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Unpinned Nanopore OS Scheduler & NUMA Telemetry Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
    <style>
        :root {{
            --bg: #0f172a;
            --card: #1e293b;
            --text: #f8fafc;
            --muted: #94a3b8;
            --accent: #38bdf8;
            --border: #334155;
        }}
        body {{
            margin: 0;
            padding: 24px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
        }}
        h1 {{ margin: 0 0 8px 0; font-size: 24px; color: var(--accent); }}
        .subtitle {{ color: var(--muted); margin-bottom: 24px; font-size: 14px; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-bottom: 24px;
        }}
        .card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 16px;
        }}
        .card-full {{
            grid-column: 1 / -1;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th, td {{
            border-bottom: 1px solid var(--border);
            padding: 10px 8px;
            text-align: left;
        }}
        th {{ color: var(--accent); font-weight: 600; background: #0f172a; }}
        .badge-ok {{
            background: rgba(34, 197, 94, 0.2);
            color: #4ade80;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 600;
        }}
        code {{
            background: #0f172a;
            padding: 2px 5px;
            border-radius: 4px;
            color: #fbbf24;
        }}
    </style>
</head>
<body>
    <h1>Unpinned Baseline: Linux CFS Scheduler & NUMA Telemetry Report</h1>
    <div class="subtitle">
        Hardware: Dual-Socket Intel Xeon Gold 6342 (94 Online Threads: 0-93 | NUMA Node 0 = Even CPUs, NUMA Node 1 = Odd CPUs) + NVIDIA A16 GPU<br>
        Configuration: Pure Default Unpinned State (<code>Cpus_allowed_list: 0-93</code>, <code>Mems_allowed_list: 0-1</code>, Native Tool Thread Defaults, 200ms /proc Sampling)
    </div>

    <div class="card card-full" style="margin-bottom: 20px; overflow-x: auto;">
        <h3 style="margin-top:0;">Stage-by-Stage OS Scheduler & NUMA Summary</h3>
        <table>
            <thead>
                <tr>
                    <th>Stage</th>
                    <th>Status</th>
                    <th>Duration</th>
                    <th>Spawned Threads</th>
                    <th>Seq % / Parallel %</th>
                    <th>Avg Running Threads</th>
                    <th>Core Migrations</th>
                    <th>Cross-NUMA Bounces</th>
                    <th>Context Switches (Vol / Invol)</th>
                    <th>NUMA RAM Pages (N0 / N1)</th>
                    <th>NUMA CPU Exec (N0 / N1)</th>
                    <th>Est. Remote Mem Access</th>
                    <th>Affinity Masks</th>
                </tr>
            </thead>
            <tbody>
                {table_rows_html}
            </tbody>
        </table>
    </div>

    <div class="grid">
        <div class="card">
            <div id="chart_seq_par" style="height: 380px;"></div>
        </div>
        <div class="card">
            <div id="chart_migrations" style="height: 380px;"></div>
        </div>
        <div class="card">
            <div id="chart_preemptions" style="height: 380px;"></div>
        </div>
        <div class="card">
            <div id="chart_numa_mismatch" style="height: 380px;"></div>
        </div>
        <div class="card card-full">
            <div id="chart_core_heatmap" style="height: 420px;"></div>
        </div>
    </div>

    <script>
        const stages = {json.dumps(stages)};
        const darkLayout = {{
            paper_bgcolor: '#1e293b',
            plot_bgcolor: '#0f172a',
            font: {{ color: '#f8fafc', size: 12 }},
            margin: {{ t: 50, l: 60, r: 30, b: 80 }},
            legend: {{ orientation: 'h', y: -0.22 }}
        }};

        // 1. Sequential vs Parallel Execution Ratio & Concurrency
        Plotly.newPlot('chart_seq_par', [
            {{ x: stages, y: {json.dumps(seq_pcts)}, name: 'Sequential Bottleneck (<=1 Running Thread) %', type: 'bar', marker: {{ color: '#f97316' }} }},
            {{ x: stages, y: {json.dumps(par_pcts)}, name: 'Parallel Execution (>1 Running Threads) %', type: 'bar', marker: {{ color: '#22c55e' }} }},
            {{ x: stages, y: {json.dumps(peak_run)}, name: 'Peak Running Concurrency (Threads)', type: 'scatter', mode: 'lines+markers', yaxis: 'y2', line: {{ color: '#38bdf8', width: 3 }} }}
        ], {{
            ...darkLayout,
            title: '1. Sequential Bottleneck vs. Parallel Execution Time (%) & Peak Concurrency',
            barmode: 'stack',
            yaxis: {{ title: 'Wall-Clock Time (%)', range: [0, 105] }},
            yaxis2: {{ title: 'Peak Running Threads', overlaying: 'y', side: 'right' }}
        }});

        // 2. Core Migrations vs Cross-NUMA Socket Bounces
        Plotly.newPlot('chart_migrations', [
            {{ x: stages, y: {json.dumps(migrations)}, name: 'Total CPU Core Migrations', type: 'bar', marker: {{ color: '#60a5fa' }} }},
            {{ x: stages, y: {json.dumps(bounces)}, name: 'Cross-NUMA Socket Bounces (Node 0 <-> Node 1)', type: 'bar', marker: {{ color: '#f43f5e' }} }}
        ], {{
            ...darkLayout,
            title: '2. CFS Thread Core Migrations vs. Cross-NUMA Socket Bounces',
            barmode: 'group',
            yaxis: {{ title: 'Migration Event Count (200ms ticks)' }}
        }});

        // 3. Voluntary vs Involuntary Preemptions
        Plotly.newPlot('chart_preemptions', [
            {{ x: stages, y: {json.dumps(vol_sw)}, name: 'Voluntary Context Switches (I/O & Lock Waits)', type: 'bar', marker: {{ color: '#a78bfa' }} }},
            {{ x: stages, y: {json.dumps(invol_sw)}, name: 'Involuntary Preemptions (Time-Slice / Contention)', type: 'bar', marker: {{ color: '#facc15' }} }}
        ], {{
            ...darkLayout,
            title: '3. Voluntary Context Switches vs. Involuntary Preemptions (Log Scale)',
            barmode: 'group',
            yaxis: {{ title: 'Switch Count (log scale)', type: 'log' }}
        }});

        // 4. NUMA Memory Page Allocation vs CPU Execution Affiliation
        Plotly.newPlot('chart_numa_mismatch', [
            {{ x: stages, y: {json.dumps(n0_mem)}, name: 'NUMA Node 0 RAM Pages (%)', type: 'bar', marker: {{ color: '#14b8a6' }} }},
            {{ x: stages, y: {json.dumps(n1_mem)}, name: 'NUMA Node 1 RAM Pages (%)', type: 'bar', marker: {{ color: '#0ea5e9' }} }},
            {{ x: stages, y: {json.dumps(n0_exec)}, name: 'NUMA Node 0 CPU Exec (%)', type: 'scatter', mode: 'lines+markers', line: {{ color: '#f472b6', width: 3 }} }},
            {{ x: stages, y: {json.dumps(remote_est)}, name: 'Est. Cross-NUMA Remote Access (%)', type: 'scatter', mode: 'lines+markers', line: {{ color: '#ef4444', width: 3, dash: 'dot' }} }}
        ], {{
            ...darkLayout,
            title: '4. NUMA Memory Allocation (N0/N1) vs. CPU Execution Affiliation & Remote Access',
            barmode: 'stack',
            yaxis: {{ title: 'Percentage (%)', range: [0, 105] }}
        }});

        // 5. Per-Core Hit Heatmap across 0-93 Online Cores
        Plotly.newPlot('chart_core_heatmap', [
            {{
                z: {json.dumps(heatmap_z)},
                x: {json.dumps(core_labels)},
                y: stages,
                type: 'heatmap',
                colorscale: 'Viridis',
                colorbar: {{ title: 'Thread Hits' }}
            }}
        ], {{
            ...darkLayout,
            title: '5. Linux CFS Default Core Assignment Heatmap Across Online Cores (CPU 0 - CPU 93)',
            xaxis: {{ title: 'Logical CPU Core ID (Even = NUMA Node 0, Odd = NUMA Node 1)' }},
            yaxis: {{ title: 'Pipeline Stage' }}
        }});
    </script>
</body>
</html>
"""
    with open(out_html_path, "w") as f:
        f.write(html)


def run_stage(stage_name, cmd, ts_writer, ts_file, log_dir):
    print(f"\n==================================================================")
    print(f"[UNPINNED BASELINE] >>> Starting Stage: {stage_name}")
    print(f"Command: {cmd}")
    print(f"==================================================================")

    stage_log = os.path.join(log_dir, f"{stage_name}.log")
    start_time = time.time()

    with open(stage_log, "w") as out_f:
        proc = subprocess.Popen(cmd, shell=True, stdout=out_f, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        profiler = UnpinnedStageProfiler(proc.pid, stage_name, ts_writer, ts_file, interval=0.2)
        mon_thread = threading.Thread(target=profiler.monitor)
        mon_thread.start()

        rc = proc.wait()
        profiler.stop_event.set()
        mon_thread.join()

    duration = time.time() - start_time
    summary = profiler.summarize(duration, rc)
    print(
        f"[UNPINNED BASELINE] <<< Finished {stage_name} in {duration:.2f}s | "
        f"Status: {summary['status']} | Spawned Threads: {summary['total_spawned_threads']} | "
        f"Parallel: {summary['parallel_time_pct']:.1f}% | Migrations: {summary['total_core_migrations']} "
        f"(NUMA Bounces: {summary['cross_numa_socket_bounces']}) | "
        f"NUMA Mem N0/N1: {summary['numa_node0_mem_pct']:.1f}%/{summary['numa_node1_mem_pct']:.1f}%"
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description="Unpinned Baseline OS Scheduler & NUMA Telemetry Profiler")
    parser.add_argument("--base-dir", type=str, default=os.path.expanduser("~/fyp-nanopore-os-benchmark"))
    parser.add_argument("--gpu-device", type=str, default="cuda:1")
    args = parser.parse_args()

    extra_paths = [
        os.path.expanduser("~/miniconda3/envs/ont_benchmark/bin"),
        os.path.expanduser("~/.local/bin"),
    ]
    os.environ["PATH"] = ":".join(extra_paths) + ":" + os.environ.get("PATH", "")

    base = args.base_dir
    fast5_dir = os.path.join(base, "datasets/fast5")
    fastq_dir = os.path.join(base, "datasets/fastq")
    ref_fasta = os.path.join(base, "datasets/reference/reference.fasta")
    out_dir = os.path.join(base, "results/unpinned_baseline")
    log_dir = os.path.join(base, "logs/unpinned_baseline")

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    ts_csv_path = os.path.join(log_dir, "timeseries_scheduler_numa.csv")
    summary_csv_path = os.path.join(log_dir, "stage_scheduler_summary.csv")
    summary_json_path = os.path.join(log_dir, "stage_scheduler_summary.json")
    heatmap_csv_path = os.path.join(log_dir, "core_heatmap_distribution.csv")
    dashboard_html_path = os.path.join(log_dir, "unpinned_scheduler_dashboard.html")

    ts_headers = [
        "timestamp", "stage", "elapsed_sec", "alive_threads", "cumulative_spawned_threads",
        "running_threads_R", "sleeping_threads_S_D", "disk_wait_threads_D", "execution_mode",
        "active_cores_this_tick", "tick_core_migrations", "cumulative_core_migrations",
        "tick_cross_numa_bounces", "cumulative_cross_numa_bounces",
        "voluntary_ctxt_switches", "nonvoluntary_ctxt_switches",
        "numa_node0_pages", "numa_node1_pages", "numa_node0_mem_pct", "numa_node1_mem_pct",
        "numa_node0_cpu_pct", "numa_node1_cpu_pct", "cpus_allowed_list", "mems_allowed_list"
    ]

    summaries = []
    with open(ts_csv_path, mode="w", newline="") as ts_f:
        ts_writer = csv.writer(ts_f)
        ts_writer.writerow(ts_headers)

        # 1. Stage 00: Fast5 to POD5 (pure unpinned default, no --threads passed)
        pod5_out_dir = os.path.join(out_dir, "pod5_converted")
        os.makedirs(pod5_out_dir, exist_ok=True)
        pod5_file = os.path.join(pod5_out_dir, "converted.pod5")
        cmd_pod5 = f"pod5 convert fast5 {fast5_dir} --output {pod5_file} --recursive --force-overwrite"
        summaries.append(run_stage("00_fast5_to_pod5", cmd_pod5, ts_writer, ts_f, log_dir))

        # 2. Stage 01: Dorado Basecalling (unpinned default)
        basecalled_fq = os.path.join(out_dir, "basecalled.fastq")
        dorado_helper = os.path.join(base, "scripts/run_dorado_stage.sh")
        cmd_dorado = f'"{dorado_helper}" "{pod5_out_dir}" "{basecalled_fq}" "{args.gpu_device}" "dna_r9.4.1_450bps_fast.cfg"'
        summaries.append(run_stage("01_dorado_basecall", cmd_dorado, ts_writer, ts_f, log_dir))

        # Locate FASTQ files
        fq_files = sorted(glob.glob(os.path.join(fastq_dir, "**", "*.fastq*"), recursive=True))
        if not fq_files and os.path.exists(basecalled_fq):
            fq_files = [basecalled_fq]
        fq_input_str = " ".join(fq_files)

        # 3. Stage 02: NanoPlot QC (pure unpinned default, no -t passed)
        qc_out = os.path.join(out_dir, "qc")
        cmd_qc = f"NanoPlot --fastq {fq_input_str} -o {qc_out}"
        summaries.append(run_stage("02_nanoplot_qc", cmd_qc, ts_writer, ts_f, log_dir))

        # 4. Stage 03: Flye De-Novo Assembly (pure unpinned default, no --threads passed)
        flye_out = os.path.join(out_dir, "flye_assembly")
        cmd_flye = f"flye --nano-raw {fq_input_str} --out-dir {flye_out}"
        summaries.append(run_stage("03_flye_denovo_assembly", cmd_flye, ts_writer, ts_f, log_dir))

        # 5. Stage 04: Minimap2 Alignment (pure unpinned default, no -t passed)
        flye_assembly_fasta = os.path.join(flye_out, "assembly.fasta")
        active_ref = ref_fasta if os.path.exists(ref_fasta) else flye_assembly_fasta
        sam_out = os.path.join(out_dir, "aligned.sam")
        bam_out = os.path.join(out_dir, "sorted.bam")
        cmd_align = f"minimap2 -ax map-ont {active_ref} {fq_input_str} > {sam_out}"
        summaries.append(run_stage("04_minimap2_align", cmd_align, ts_writer, ts_f, log_dir))

        # 6. Stage 05: Samtools Sort & Index (pure unpinned default, no -@ passed)
        cmd_sort = f"samtools sort -o {bam_out} {sam_out} && samtools index {bam_out}"
        summaries.append(run_stage("05_samtools_sort_index", cmd_sort, ts_writer, ts_f, log_dir))

        if os.path.exists(sam_out):
            os.remove(sam_out)

    # Write stage_scheduler_summary.csv
    summary_fields = [
        "stage", "status", "duration_sec", "samples_collected",
        "total_spawned_threads", "max_concurrent_threads_alive", "unique_active_cores_count",
        "top_favored_cores", "sequential_time_pct", "parallel_time_pct",
        "avg_running_threads", "peak_running_threads", "avg_sleeping_threads",
        "total_core_migrations", "cross_numa_socket_bounces", "numa_bounce_ratio_pct",
        "voluntary_ctxt_switches", "nonvoluntary_ctxt_switches",
        "voluntary_switch_pct", "involuntary_preemption_pct",
        "numa_node0_pages_avg", "numa_node1_pages_avg",
        "numa_node0_pages_peak", "numa_node1_pages_peak",
        "numa_node0_mem_pct", "numa_node1_mem_pct",
        "numa_node0_cpu_exec_pct", "numa_node1_cpu_exec_pct",
        "estimated_numa_local_access_pct", "estimated_numa_remote_access_pct",
        "cpus_allowed_list", "mems_allowed_list"
    ]
    with open(summary_csv_path, mode="w", newline="") as sf:
        writer = csv.DictWriter(sf, fieldnames=summary_fields, extrasaction="ignore")
        writer.writeheader()
        for s in summaries:
            writer.writerow(s)

    # Write stage_scheduler_summary.json
    with open(summary_json_path, mode="w") as jf:
        json.dump(summaries, jf, indent=2)

    # Write core_heatmap_distribution.csv
    with open(heatmap_csv_path, mode="w", newline="") as hf:
        hw = csv.writer(hf)
        hw.writerow(["stage", "metric"] + [f"cpu_{c}" for c in range(NUM_CORES)])
        for s in summaries:
            hw.writerow([s["stage"], "all_thread_hits"] + [s["core_hits"].get(c, 0) for c in range(NUM_CORES)])
            hw.writerow([s["stage"], "running_R_hits"] + [s["core_running_hits"].get(c, 0) for c in range(NUM_CORES)])

    # Generate HTML Dashboard
    generate_html_dashboard(summaries, dashboard_html_path)

    print("\n==================================================================")
    print("[UNPINNED BASELINE] Complete! Outputs saved to:")
    print(f"  - Time-series CSV: {ts_csv_path}")
    print(f"  - Stage Summary CSV: {summary_csv_path}")
    print(f"  - Stage Summary JSON: {summary_json_path}")
    print(f"  - Core Heatmap CSV: {heatmap_csv_path}")
    print(f"  - Interactive Dashboard HTML: {dashboard_html_path}")
    print("==================================================================")


if __name__ == "__main__":
    main()

