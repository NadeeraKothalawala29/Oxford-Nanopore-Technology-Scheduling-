# Oxford Nanopore Technology Scheduling & OS Benchmark

Fourth-Year Project (FYP) investigating Linux kernel OS scheduling, thread concurrency, context switches, CPU core migrations, and memory behaviors during Oxford Nanopore Technologies (ONT) bioinformatics workloads.

---

## Repository Structure

```text
├── Academic/               # FYP project documentation, assessment rubrics, and presentations
│   ├── assessment/
│   └── Presentations/
├── scripts/                # Benchmark execution and OS scheduler profiling scripts
│   ├── benchmark_runner.py # Multi-stage ONT pipeline benchmark runner & telemetry logger
│   ├── run_exp1.sh         # Isolated baseline benchmark runner script (Experiment 1)
│   ├── run_dorado_stage.sh # Standalone Dorado basecaller client/server GPU wrapper
│   └── trace_scheduler.sh  # Kernel scheduler event tracer & FlameGraph generator wrapper
├── .gitignore              # Excludes heavy raw datasets, BAM/FASTQ outputs, and raw trace data
└── README.md
```

---

## Pipeline Stages Profiled

1. **Stage 00 (Fast5 to POD5 Conversion)**: `pod5 convert fast5`
2. **Stage 01 (Basecalling)**: Dorado GPU Basecall Server + Client
3. **Stage 02 (Quality Control)**: `NanoPlot`
4. **Stage 03 (De-Novo Assembly)**: `flye`
5. **Stage 04 (Sequence Alignment)**: `minimap2`
6. **Stage 05 (BAM Sorting & Indexing)**: `samtools`

---

## Quick Start

### 1. Environment Setup
Create and activate the Conda benchmarking environment:
```bash
conda create -n ont_benchmark -c conda-forge -c bioconda python=3.10 psutil nanoplot flye minimap2 samtools pod5
conda activate ont_benchmark
```

### 2. Running Baseline Benchmark
```bash
bash scripts/run_exp1.sh
```

### 3. Running with OS Scheduler Profiling & FlameGraphs
```bash
python3 scripts/benchmark_runner.py --run-tag sched_profile --iterations 1 --threads 16 --gpu-device cuda:1 --trace-scheduler
```
Generated FlameGraphs (`.html`) and scheduler latency reports (`.txt`) will be saved in `logs/`.
