# Oxford Nanopore Pipeline Reference & Benchmark Workflows

This document describes the bioinformatics pipelines, stage implementations, and toolchains evaluated in this OS scheduling and resource benchmark study.

Rather than committing heavy third-party cloned repositories (which contain separate `.git` histories, container bundles, and test data), this repository captures the **orchestration scripts**, **exact execution commands**, and **telemetry outputs** that characterize how these workflows behave inside the Linux kernel.

---

## 1. Modular ONT Benchmark Pipeline (Primary Testbed)

The primary benchmark workflow is implemented as an end-to-end, multi-stage pipeline orchestrated by [`scripts/benchmark_runner.py`](../scripts/benchmark_runner.py) and [`scripts/run_unpinned_baseline.sh`](../scripts/run_unpinned_baseline.sh). It represents the complete lifecycle of Oxford Nanopore sequencing data from raw electrical current signals to an assembled and aligned genome:

```
[Raw Electrical Signals: .fast5]
             │
             ▼
┌────────────────────────────────────────┐
│ Stage 0: 00_fast5_to_pod5              │  Tool: pod5 convert fast5
│ Compute Profile: I/O + Zstd Comp.      │  Output: compressed .pod5 signal
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│ Stage 1: 01_dorado_basecall            │  Tool: Dorado Basecaller Server/Client
│ Compute Profile: GPU Matrix Math + I/O │  Device: NVIDIA A16 GPU (cuda:1)
└──────────────────┬─────────────────────┘  Output: basecalled .fastq (22,890 reads)
                   │
                   ▼
┌────────────────────────────────────────┐
│ Stage 2: 02_nanoplot_qc                │  Tool: NanoPlot
│ Compute Profile: Multi-core CPU Burst  │  Output: HTML QC report, NanoStats.txt
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│ Stage 3: 03_flye_denovo_assembly       │  Tool: Flye de-novo assembler
│ Compute Profile: High Memory (RAM RSS) │  Output: assembly.fasta, contig graph
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│ Stage 4: 04_minimap2_align             │  Tool: minimap2 -ax map-ont
│ Compute Profile: Hash Index Alignment  │  Output: aligned .sam file
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│ Stage 5: 05_samtools_sort_index        │  Tool: samtools sort & samtools index
│ Compute Profile: Block Compression     │  Output: coordinate-sorted .bam & .bai
└────────────────────────────────────────┘
```

### Stage Details & Tool Configurations

| Stage Name | Software Tool | Primary Function | Server Resource Profile | Output Artifacts |
| :--- | :--- | :--- | :--- | :--- |
| `00_fast5_to_pod5` | `pod5` (v0.3.16) | Converts raw FAST5 current files to columnar POD5 format | Multi-threaded file I/O & IPC; moderate CPU (~1,099% peak) | `converted.pod5` |
| `01_dorado_basecall` | `dorado` (v0.5.3) | Neural network basecalling on NVIDIA A16 GPU (`cuda:1`, model `dna_r9.4.1_e8_fast@v3.4`) | High GPU tensor utilization; 114 host threads managing I/O; 2.1 GB RAM | `basecalled.fastq` (13.04 Mb bases) |
| `02_nanoplot_qc` | `NanoPlot` (v1.43.0) | Read length, quality score calculation, and interactive HTML visualization | Massive thread burst (**989 spawned threads** across all 94 cores; **8,510% peak CPU**) | `NanoPlot-report.html`, `NanoStats.txt` |
| `03_flye_denovo_assembly` | `Flye` (v2.9.4) | Repeat-graph de-novo genome assembly from long noisy reads | **Longest runtime (62.3s)**; **Highest RAM consumption (8.34 GB RSS)** | `assembly.fasta`, `assembly_graph.gfa` |
| `04_minimap2_align` | `minimap2` (v2.28) | Maps long reads back to assembled contigs via seed-and-chain | Compute-bound string matching; low memory (~40 MB) | `aligned.sam` |
| `05_samtools_sort_index` | `samtools` (v1.20) | Sorts alignments by coordinate and builds BAM index (`.bai`) | Streaming BGZF block compression; low memory (~70 MB) | `sorted.bam`, `sorted.bam.bai` |

---

## 2. Standardized Community Pipelines Evaluated

In addition to our native modular benchmark suite, the repository references six industry-standard Nanopore workflows from **EPI2ME Labs (Oxford Nanopore Technologies)** and **nf-core**:

1. **`wf-basecalling`** (EPI2ME Labs):
   - Automated Dorado and Guppy execution with demultiplexing, barcode classification, and quality filtering.
2. **`wf-alignment`** (EPI2ME Labs):
   - Reference mapping using Minimap2 with automated BAM sorting, indexing, and alignment statistics generation.
3. **`wf-bacterial-genomes`** (EPI2ME Labs):
   - Complete de-novo bacterial assembly workflow incorporating Flye/Miniasm, Medaka consensus polishing, and assembly evaluation.
4. **`wf-metagenomics`** (EPI2ME Labs):
   - Taxonomic classification and abundance estimation of complex microbial communities using Kraken2 and Bracken.
5. **`nanoseq`** (nf-core):
   - Comprehensive community pipeline supporting DNA/RNA sequencing, basecalling, QC, demultiplexing, alignment, and variant calling.
6. **`nanogo`**:
   - Lightweight pipeline tailored for rapid turnaround QC and read mapping in low-resource environments.

---

## 3. How Pipelines Are Executed & Profiled

All pipeline stages are executed under active Linux kernel telemetry logging:

### A. Pure Unpinned Default Run (Scheduler & NUMA Profiling)
```bash
# Runs modular stages with unpinned CFS thread placement across all 94 online cores
bash scripts/run_unpinned_baseline.sh
```
- Telemetry sampled via `scripts/unpinned_scheduler_profiler.py` polling `/proc/<pid>/task/<tid>/stat`, `status`, and `/proc/<pid>/numa_maps` every 200 ms.
- Output reports: `logs/unpinned_baseline/stage_scheduler_summary.csv`, `unpinned_scheduler_dashboard.html`.

### B. Baseline 16-Thread Resource Profiling
```bash
# Runs pipeline iterations with 16 worker threads, logging CPU %, RAM (RSS), and I/O
bash scripts/run_exp1.sh
```
- Telemetry logged via `scripts/benchmark_runner.py` sampling at 1-second intervals.
- Output reports: `logs/summary_baseline_1x_*.csv`, `logs/timeseries_baseline_1x_*.csv`.

