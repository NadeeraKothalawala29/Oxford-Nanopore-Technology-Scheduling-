#!/usr/bin/env python3
import os
import sys
import glob
import time
import csv
import argparse
import subprocess
import threading
from datetime import datetime
import psutil

class StageProfiler:
    """Monitors a process and all its children recursively at a fixed interval."""
    def __init__(self, pid, run_tag, iteration, pipeline_name, stage_name, timeseries_csv, interval=0.1):
        self.pid = pid
        self.run_tag = run_tag
        self.iteration = iteration
        self.pipeline_name = pipeline_name
        self.stage_name = stage_name
        self.timeseries_csv = timeseries_csv
        self.interval = interval
        self.stop_event = threading.Event()
        self.proc_cache = {}
        
        self.peak_cpu = 0.0
        self.peak_rss_mb = 0.0
        self.max_threads = 0
        self.max_procs = 0
        self.total_vol_ctx = 0
        self.total_invol_ctx = 0
        self.cores_seen = set()

    def _get_process_tree(self, parent_proc):
        raw_procs = [parent_proc]
        try:
            raw_procs.extend(parent_proc.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        cached_procs = []
        active_keys = set()
        for p in raw_procs:
            try:
                key = (p.pid, p.create_time())
                active_keys.add(key)
                if key not in self.proc_cache:
                    p.cpu_percent(interval=None)
                    self.proc_cache[key] = p
                cached_procs.append(self.proc_cache[key])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        for k in list(self.proc_cache.keys()):
            if k not in active_keys:
                del self.proc_cache[k]

        return cached_procs

    def monitor(self):
        try:
            parent = psutil.Process(self.pid)
        except psutil.NoSuchProcess:
            return

        self._get_process_tree(parent)

        with open(self.timeseries_csv, mode='a', newline='') as f:
            writer = csv.writer(f)
            
            while not self.stop_event.is_set():
                time.sleep(self.interval)
                if not parent.is_running() or parent.status() == psutil.STATUS_ZOMBIE:
                    break

                procs = self._get_process_tree(parent)
                
                total_cpu = 0.0
                total_rss = 0
                total_vms = 0
                total_threads = 0
                vol_ctx = 0
                invol_ctx = 0
                io_read_bytes = 0
                io_write_bytes = 0
                active_cores = set()
                alive_procs = 0

                for p in procs:
                    try:
                        with p.oneshot():
                            alive_procs += 1
                            total_cpu += p.cpu_percent(interval=None)
                            mem = p.memory_info()
                            total_rss += mem.rss
                            total_vms += mem.vms
                            total_threads += p.num_threads()
                            
                            ctx = p.num_ctx_switches()
                            vol_ctx += ctx.voluntary
                            invol_ctx += ctx.involuntary
                            
                            if hasattr(p, 'cpu_num'):
                                active_cores.add(p.cpu_num())
                                
                            io = p.io_counters()
                            io_read_bytes += io.read_bytes
                            io_write_bytes += io.write_bytes
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue

                rss_mb = total_rss / (1024 * 1024)
                vms_mb = total_vms / (1024 * 1024)
                read_mb = io_read_bytes / (1024 * 1024)
                write_mb = io_write_bytes / (1024 * 1024)

                self.peak_cpu = max(self.peak_cpu, total_cpu)
                self.peak_rss_mb = max(self.peak_rss_mb, rss_mb)
                self.max_threads = max(self.max_threads, total_threads)
                self.max_procs = max(self.max_procs, alive_procs)
                self.total_vol_ctx = max(self.total_vol_ctx, vol_ctx)
                self.total_invol_ctx = max(self.total_invol_ctx, invol_ctx)
                self.cores_seen.update(active_cores)

                writer.writerow([
                    datetime.now().isoformat(),
                    self.run_tag,
                    self.iteration,
                    self.pipeline_name,
                    self.stage_name,
                    round(total_cpu, 2),
                    round(rss_mb, 2),
                    round(vms_mb, 2),
                    total_threads,
                    alive_procs,
                    len(active_cores),
                    vol_ctx,
                    invol_ctx,
                    round(read_mb, 2),
                    round(write_mb, 2)
                ])
                f.flush()


def run_and_profile_stage(cmd, run_tag, iteration, pipeline_name, stage_name, ts_csv, summary_csv, log_dir, trace_scheduler=False):
    if trace_scheduler:
        log_prefix = os.path.join(log_dir, f"{run_tag}_iter{iteration}_{stage_name}")
        wrapper_script = os.path.expanduser("~/fyp-nanopore-os-benchmark/scripts/trace_scheduler.sh")
        cmd = f'LOG_PREFIX="{log_prefix}" "{wrapper_script}" bash -c {subprocess.list2cmdline([cmd])}'

    print(f"\n[{run_tag} | Iter {iteration}] >>> Starting Stage: {stage_name}")
    print(f"Command: {cmd}")
    
    stage_log = os.path.join(log_dir, f"{run_tag}_iter{iteration}_{pipeline_name}_{stage_name}.log")
    start_time = time.time()
    
    with open(stage_log, "w") as out_f:
        proc = subprocess.Popen(cmd, shell=True, stdout=out_f, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        
        profiler = StageProfiler(proc.pid, run_tag, iteration, pipeline_name, stage_name, ts_csv, interval=0.1)
        mon_thread = threading.Thread(target=profiler.monitor)
        mon_thread.start()
        
        return_code = proc.wait()
        profiler.stop_event.set()
        mon_thread.join()

    duration_sec = time.time() - start_time
    status = "SUCCESS" if return_code == 0 else f"FAILED({return_code})"
    print(f"[{run_tag} | Iter {iteration}] <<< Finished {stage_name} in {duration_sec:.2f}s | Status: {status} | Peak CPU: {profiler.peak_cpu:.1f}% | Peak RAM: {profiler.peak_rss_mb:.1f} MB | Max Threads: {profiler.max_threads}")

    with open(summary_csv, mode='a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(),
            run_tag,
            iteration,
            pipeline_name,
            stage_name,
            status,
            round(duration_sec, 3),
            round(profiler.peak_cpu, 2),
            round(profiler.peak_rss_mb, 2),
            profiler.max_threads,
            profiler.max_procs,
            len(profiler.cores_seen),
            profiler.total_vol_ctx,
            profiler.total_invol_ctx
        ])
    return return_code


def main():
    extra_paths = [
        os.path.expanduser("~/miniconda3/envs/ont_benchmark/bin"),
        os.path.expanduser("~/.local/bin"),
    ]
    os.environ["PATH"] = ":".join(extra_paths) + ":" + os.environ.get("PATH", "")
    parser = argparse.ArgumentParser(description="FYP Nanopore Multi-Pipeline OS Profiler (De-Novo + Alignment)")
    parser.add_argument("--run-tag", type=str, default="baseline", help="Identifier for this run (e.g. baseline, concurrent_1)")
    parser.add_argument("--iterations", type=int, default=2, help="Number of times to repeat the benchmark")
    parser.add_argument("--threads", type=int, default=16, help="Threads to allocate per tool")
    parser.add_argument("--gpu-device", type=str, default="cuda:1", help="CUDA device for Dorado (e.g., cuda:1, cuda:2)")
    parser.add_argument("--base-dir", type=str, default=os.path.expanduser("~/fyp-nanopore-os-benchmark"))
    parser.add_argument("--dorado-model", type=str, default="/opt/ont/dorado-models/dna_r10.4.1_e8.2_400bps_fast@v4.3.0", help="Path to Dorado model")
    parser.add_argument("--trace-scheduler", action="store_true", help="Wrap pipeline stages with trace_scheduler.sh for FlameGraph and latency profiling")
    args = parser.parse_args()

    base = args.base_dir
    fast5_dir = os.path.join(base, "datasets/fast5")
    fastq_dir = os.path.join(base, "datasets/fastq")
    ref_fasta = os.path.join(base, "datasets/reference/reference.fasta")
    results_dir = os.path.join(base, "results", args.run_tag)
    log_dir = os.path.join(base, "logs")

    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_csv = os.path.join(log_dir, f"timeseries_{args.run_tag}_{run_timestamp}.csv")
    summary_csv = os.path.join(log_dir, f"summary_{args.run_tag}_{run_timestamp}.csv")

    with open(ts_csv, mode='w', newline='') as f:
        csv.writer(f).writerow([
            "timestamp", "run_tag", "iteration", "pipeline", "stage",
            "cpu_percent", "rss_mb", "vms_mb", "threads", "processes",
            "active_cores_count", "vol_ctx_switches", "invol_ctx_switches",
            "io_read_mb", "io_write_mb"
        ])

    with open(summary_csv, mode='w', newline='') as f:
        csv.writer(f).writerow([
            "timestamp", "run_tag", "iteration", "pipeline", "stage", "status",
            "duration_sec", "peak_cpu_percent", "peak_rss_mb",
            "max_threads", "max_processes", "unique_cores_used",
            "total_vol_ctx", "total_invol_ctx"
        ])

    for i in range(1, args.iterations + 1):
        print(f"\n=======================================================")
        print(f"   [{args.run_tag}] STARTING ITERATION {i}/{args.iterations}")
        print(f"=======================================================")

        iter_out = os.path.join(results_dir, f"iter_{i}")
        os.makedirs(iter_out, exist_ok=True)
        basecalled_fq = os.path.join(iter_out, "basecalled.fastq")

        # STAGE 0 & 1: Fast5 -> POD5 -> Dorado Basecalling
        fast5_files = glob.glob(os.path.join(fast5_dir, "**", "*.fast5"), recursive=True)
        if fast5_files:
            pod5_out_dir = os.path.join(iter_out, "pod5_converted")
            os.makedirs(pod5_out_dir, exist_ok=True)
            pod5_file = os.path.join(pod5_out_dir, "converted.pod5")
            
            cmd_pod5 = f"pod5 convert fast5 {fast5_dir} --output {pod5_file} --threads {args.threads} --recursive --force-overwrite"
            run_and_profile_stage(cmd_pod5, args.run_tag, i, "modular_ont", "00_fast5_to_pod5", ts_csv, summary_csv, log_dir, trace_scheduler=args.trace_scheduler)

            if os.path.exists("/opt/ont/dorado/bin/dorado") and os.path.exists(args.dorado_model):
                cmd_dorado = f"/opt/ont/dorado/bin/dorado basecaller {args.dorado_model} {pod5_out_dir} --device {args.gpu_device} --emit-fastq > {basecalled_fq}"
                rc = run_and_profile_stage(cmd_dorado, args.run_tag, i, "modular_ont", "01_dorado_basecall", ts_csv, summary_csv, log_dir, trace_scheduler=args.trace_scheduler)
                # Fallback to R9.4.1 model if R10 model fails due to chemistry mismatch
                if rc != 0 or (os.path.exists(basecalled_fq) and os.path.getsize(basecalled_fq) == 0):
                    r9_model = "/opt/ont/dorado-models/dna_r9.4.1_e8_fast@v3.4"
                    print(f"[INFO] Retrying Dorado with R9.4.1 model: {r9_model}")
                    cmd_dorado_r9 = f"/opt/ont/dorado/bin/dorado basecaller {r9_model} {pod5_out_dir} --device {args.gpu_device} --emit-fastq > {basecalled_fq}"
                    run_and_profile_stage(cmd_dorado_r9, args.run_tag, i, "modular_ont", "01_dorado_basecall_r9", ts_csv, summary_csv, log_dir, trace_scheduler=args.trace_scheduler)
            elif os.path.exists("/opt/ont/dorado/bin/dorado_basecall_server"):
                dorado_helper = os.path.join(base, "scripts/run_dorado_stage.sh")
                cmd_dorado_srv = f'"{dorado_helper}" "{pod5_out_dir}" "{basecalled_fq}" "{args.gpu_device}" "dna_r9.4.1_450bps_fast.cfg"'
                run_and_profile_stage(cmd_dorado_srv, args.run_tag, i, "modular_ont", "01_dorado_basecall", ts_csv, summary_csv, log_dir, trace_scheduler=args.trace_scheduler)

        # Locate FASTQ files (prefer uploaded fastq/, otherwise use Dorado output)
        fq_files = []
        for ext in ("*.fastq", "*.fastq.gz", "*.fq", "*.fq.gz"):
            fq_files.extend(glob.glob(os.path.join(fastq_dir, "**", ext), recursive=True))
        
        if not fq_files and os.path.exists(basecalled_fq) and os.path.getsize(basecalled_fq) > 0:
            fq_files = [basecalled_fq]

        if not fq_files:
            print("[ERROR] No FASTQ files found in datasets/fastq/ and none generated by Dorado. Check dataset paths.")
            continue

        fq_input_str = " ".join(fq_files)

        # STAGE 2: Quality Control (NanoPlot)
        qc_out = os.path.join(iter_out, "qc")
        cmd_qc = f"NanoPlot -t {args.threads} --fastq {fq_input_str} -o {qc_out}"
        run_and_profile_stage(cmd_qc, args.run_tag, i, "modular_ont", "02_nanoplot_qc", ts_csv, summary_csv, log_dir, trace_scheduler=args.trace_scheduler)

        # STAGE 3: De-Novo Assembly (Flye)
        flye_out = os.path.join(iter_out, "flye_assembly")
        cmd_flye = f"flye --nano-raw {fq_input_str} --out-dir {flye_out} --threads {args.threads}"
        run_and_profile_stage(cmd_flye, args.run_tag, i, "modular_ont", "03_flye_denovo_assembly", ts_csv, summary_csv, log_dir, trace_scheduler=args.trace_scheduler)

        # Determine Reference for Alignment (either external reference.fasta OR Flye's de-novo assembly.fasta)
        flye_assembly_fasta = os.path.join(flye_out, "assembly.fasta")
        active_ref = ref_fasta if os.path.exists(ref_fasta) else (flye_assembly_fasta if os.path.exists(flye_assembly_fasta) else None)

        # STAGE 4 & 5: Sequence Alignment (Minimap2) & BAM Sorting (Samtools)
        if active_ref:
            sam_out = os.path.join(iter_out, "aligned.sam")
            bam_out = os.path.join(iter_out, "sorted.bam")

            cmd_align = f"minimap2 -ax map-ont -t {args.threads} {active_ref} {fq_input_str} > {sam_out}"
            run_and_profile_stage(cmd_align, args.run_tag, i, "modular_ont", "04_minimap2_align", ts_csv, summary_csv, log_dir, trace_scheduler=args.trace_scheduler)

            cmd_sort = f"samtools sort -@ {args.threads} -o {bam_out} {sam_out} && samtools index -@ {args.threads} {bam_out}"
            run_and_profile_stage(cmd_sort, args.run_tag, i, "modular_ont", "05_samtools_sort_index", ts_csv, summary_csv, log_dir, trace_scheduler=args.trace_scheduler)

            if os.path.exists(sam_out):
                os.remove(sam_out)
        else:
            print("[WARNING] Flye did not produce assembly.fasta (dataset may be too small/sparse for de-novo contig assembly). Creating self-reference from reads for Minimap2...")
            # Even if Flye fails on tiny test subsets, we can still benchmark Minimap2 all-vs-all overlap alignment (ava-ont)!
            paf_out = os.path.join(iter_out, "overlaps.paf")
            cmd_ava = f"minimap2 -x ava-ont -t {args.threads} {fq_input_str} {fq_input_str} > {paf_out}"
            run_and_profile_stage(cmd_ava, args.run_tag, i, "modular_ont", "04_minimap2_all_vs_all", ts_csv, summary_csv, log_dir, trace_scheduler=args.trace_scheduler)
            if os.path.exists(paf_out):
                os.remove(paf_out)

    print(f"\n[{args.run_tag}] Benchmark Complete!")
    print(f"Time-series telemetry: {ts_csv}")
    print(f"Stage summary metrics: {summary_csv}")

if __name__ == "__main__":
    main()