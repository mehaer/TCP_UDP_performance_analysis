#!/usr/bin/env python3
"""
run_experiments.py
==================
Single entry point for the TCP/UDP benchmark assignment.

Modes:
  1. Full run (default) — starts server+client locally, collects CSVs, plots
  2. --plots-only       — skip experiments, regenerate plots from existing CSVs
  3. --results-dir DIR  — read CSVs from a custom directory and plot

Usage:
  # Run everything locally (single machine):
  python3 run_experiments.py

  # After iLab two-machine run, just regenerate plots from downloaded CSVs:
  python3 run_experiments.py --plots-only

  # Plot from a specific results directory (used by run_benchmark.sh remotely):
  python3 run_experiments.py --results-dir /common/home/mdc265/tcp_udp_benchmark/results
"""

import argparse
import csv
import glob
import os
import subprocess
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Experiment parameters
# ---------------------------------------------------------------------------
PAYLOAD_SIZES       = [64, 512, 1024, 4096, 8192]
CLIENT_COUNTS       = [1, 10, 100, 1000]
REQUESTS_PER_CLIENT = 100
PORT_TCP            = 5101
PORT_UDP            = 5102

# These are set at runtime based on --results-dir / script location
RESULTS_DIR: Path
PLOTS_DIR:   Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_dirs():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)


def csv_path(proto: str, payload: int, clients: int) -> Path:
    return RESULTS_DIR / f"client_{proto}_p{payload}_c{clients}.csv"


# ---------------------------------------------------------------------------
# Local experiment runner (single-machine mode)
# ---------------------------------------------------------------------------

def run_local_experiment(proto: str, payload: int, clients: int, requests: int):
    port = PORT_TCP if proto == "tcp" else PORT_UDP
    log = str(csv_path(proto, payload, clients))
    server_log = str(RESULTS_DIR / f"server_{proto}_p{payload}_c{clients}.jsonl")

    server_cmd = [
        sys.executable, "server.py",
        "--proto", proto,
        "--bind", "127.0.0.1",
        "--port", str(port),
        "--payload-bytes", str(payload),
        "--requests", str(requests),
        "--clients", str(clients),
        "--log", server_log,
    ]
    client_cmd = [
        sys.executable, "client.py",
        "--proto", proto,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--payload-bytes", str(payload),
        "--requests", str(requests),
        "--clients", str(clients),
        "--log", log,
    ]

    print(f"  → {proto.upper()} payload={payload}B clients={clients} requests={requests}")
    srv = subprocess.Popen(server_cmd)
    time.sleep(0.5)
    try:
        subprocess.run(client_cmd, check=True, timeout=300)
    finally:
        srv.wait(timeout=15)


def run_all_experiments():
    ensure_dirs()
    total = len(PAYLOAD_SIZES) * len(CLIENT_COUNTS) * 2
    done = 0
    for proto in ("tcp", "udp"):
        for clients in CLIENT_COUNTS:
            for payload in PAYLOAD_SIZES:
                done += 1
                print(f"[{done}/{total}]")
                try:
                    run_local_experiment(proto, payload, clients, REQUESTS_PER_CLIENT)
                except subprocess.CalledProcessError as e:
                    print(f"  WARNING: experiment failed: {e}")
                time.sleep(0.5)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_csvs():
    rows = []
    pattern = str(RESULTS_DIR / "client_*.csv")
    files = glob.glob(pattern)
    if not files:
        # Also try without the client_ prefix for backwards compatibility
        files = glob.glob(str(RESULTS_DIR / "*.csv"))
    for path in files:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    row["rtt_s"]           = float(row["rtt_s"])
                    row["payload_bytes"]   = int(row["payload_bytes"])
                    row["clients"]         = int(row["clients"])
                    row["total_wall_s"]    = float(row["total_wall_s"])
                    row["throughput_MBps"] = float(row["throughput_MBps"])
                    row["connect_time_s"]  = float(row.get("connect_time_s", 0))
                    row["failed"]          = str(row.get("failed", "False")).lower() == "true"
                    rows.append(row)
                except (ValueError, KeyError):
                    pass
    return rows


def aggregate(rows, proto, payload=None, clients=None):
    subset = [r for r in rows
              if r["proto"] == proto
              and not r["failed"]
              and (payload is None or r["payload_bytes"] == payload)
              and (clients is None or r["clients"] == clients)]
    if not subset:
        return None
    rtts = [r["rtt_s"] * 1000 for r in subset]
    tput = subset[0]["throughput_MBps"]
    wall = subset[0]["total_wall_s"]
    return {
        "mean_rtt_ms":     float(np.mean(rtts)),
        "median_rtt_ms":   float(np.median(rtts)),
        "p95_rtt_ms":      float(np.percentile(rtts, 95)),
        "throughput_MBps": tput,
        "total_wall_s":    wall,
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

COLORS  = {"tcp": "#2563eb", "udp": "#dc2626"}
MARKERS = {"tcp": "o",       "udp": "s"}


def payload_label(b: int) -> str:
    return f"{b//1024}KB" if b >= 1024 else f"{b}B"


def plot_latency_vs_payload(rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    for proto in ("tcp", "udp"):
        xs, ys = [], []
        for p in PAYLOAD_SIZES:
            agg = aggregate(rows, proto, payload=p, clients=1)
            if agg:
                xs.append(payload_label(p))
                ys.append(agg["mean_rtt_ms"])
        if xs:
            ax.plot(xs, ys, marker=MARKERS[proto], color=COLORS[proto],
                    label=proto.upper(), linewidth=2)
    ax.set_title("Latency vs Payload Size (1 client, 100 requests)")
    ax.set_xlabel("Payload Size")
    ax.set_ylabel("Mean RTT (ms)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "latency_vs_payload.png", dpi=150)
    plt.close(fig)
    print("  saved latency_vs_payload.png")


def plot_throughput_vs_payload(rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    for proto in ("tcp", "udp"):
        xs, ys = [], []
        for p in PAYLOAD_SIZES:
            agg = aggregate(rows, proto, payload=p, clients=1)
            if agg:
                xs.append(payload_label(p))
                ys.append(agg["throughput_MBps"])
        if xs:
            ax.plot(xs, ys, marker=MARKERS[proto], color=COLORS[proto],
                    label=proto.upper(), linewidth=2)
    ax.set_title("Throughput vs Payload Size (1 client, 100 requests)")
    ax.set_xlabel("Payload Size")
    ax.set_ylabel("Throughput (MB/s)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "throughput_vs_payload.png", dpi=150)
    plt.close(fig)
    print("  saved throughput_vs_payload.png")


def plot_wall_vs_payload(rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    for proto in ("tcp", "udp"):
        xs, ys = [], []
        for p in PAYLOAD_SIZES:
            agg = aggregate(rows, proto, payload=p, clients=1)
            if agg:
                xs.append(payload_label(p))
                ys.append(agg["total_wall_s"])
        if xs:
            ax.plot(xs, ys, marker=MARKERS[proto], color=COLORS[proto],
                    label=proto.upper(), linewidth=2)
    ax.set_title("Time-to-Finish vs Payload Size (1 client, 100 requests)")
    ax.set_xlabel("Payload Size")
    ax.set_ylabel("Total Wall Time (s)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "wall_vs_payload.png", dpi=150)
    plt.close(fig)
    print("  saved wall_vs_payload.png")


def plot_latency_vs_clients(rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    for proto in ("tcp", "udp"):
        xs, ys = [], []
        for c in CLIENT_COUNTS:
            agg = aggregate(rows, proto, payload=512, clients=c)
            if agg:
                xs.append(c)
                ys.append(agg["mean_rtt_ms"])
        if xs:
            ax.plot(xs, ys, marker=MARKERS[proto], color=COLORS[proto],
                    label=proto.upper(), linewidth=2)
    ax.set_title("Latency vs Number of Clients (payload=512B)")
    ax.set_xlabel("Number of Clients")
    ax.set_ylabel("Mean RTT (ms)")
    ax.set_xscale("log")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "latency_vs_clients.png", dpi=150)
    plt.close(fig)
    print("  saved latency_vs_clients.png")


def plot_throughput_vs_clients(rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    for proto in ("tcp", "udp"):
        xs, ys = [], []
        for c in CLIENT_COUNTS:
            agg = aggregate(rows, proto, payload=512, clients=c)
            if agg:
                xs.append(c)
                ys.append(agg["throughput_MBps"])
        if xs:
            ax.plot(xs, ys, marker=MARKERS[proto], color=COLORS[proto],
                    label=proto.upper(), linewidth=2)
    ax.set_title("Throughput vs Number of Clients (payload=512B)")
    ax.set_xlabel("Number of Clients")
    ax.set_ylabel("Throughput (MB/s)")
    ax.set_xscale("log")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "throughput_vs_clients.png", dpi=150)
    plt.close(fig)
    print("  saved throughput_vs_clients.png")


def plot_wall_vs_clients(rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    for proto in ("tcp", "udp"):
        xs, ys = [], []
        for c in CLIENT_COUNTS:
            agg = aggregate(rows, proto, payload=512, clients=c)
            if agg:
                xs.append(c)
                ys.append(agg["total_wall_s"])
        if xs:
            ax.plot(xs, ys, marker=MARKERS[proto], color=COLORS[proto],
                    label=proto.upper(), linewidth=2)
    ax.set_title("Time-to-Finish vs Number of Clients (payload=512B)")
    ax.set_xlabel("Number of Clients")
    ax.set_ylabel("Total Wall Time (s)")
    ax.set_xscale("log")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "wall_vs_clients.png", dpi=150)
    plt.close(fig)
    print("  saved wall_vs_clients.png")


def plot_combined_bars(rows):
    """Grouped bar: mean RTT per payload size, one subplot per client count."""
    counts_available = [c for c in CLIENT_COUNTS
                        if any(aggregate(rows, p, payload=64, clients=c)
                               for p in ("tcp", "udp"))]
    if not counts_available:
        return

    payload_labels = [payload_label(p) for p in PAYLOAD_SIZES]
    n = len(counts_available)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5), sharey=False)
    if n == 1:
        axes = [axes]

    for ax, c in zip(axes, counts_available):
        x = np.arange(len(PAYLOAD_SIZES))
        w = 0.35
        tcp_vals = [((aggregate(rows, "tcp", payload=p, clients=c) or {}).get("mean_rtt_ms", 0))
                    for p in PAYLOAD_SIZES]
        udp_vals = [((aggregate(rows, "udp", payload=p, clients=c) or {}).get("mean_rtt_ms", 0))
                    for p in PAYLOAD_SIZES]
        ax.bar(x - w/2, tcp_vals, w, label="TCP", color=COLORS["tcp"], alpha=0.85)
        ax.bar(x + w/2, udp_vals, w, label="UDP", color=COLORS["udp"], alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(payload_labels)
        ax.set_title(f"{c} client(s)")
        ax.set_xlabel("Payload Size")
        ax.set_ylabel("Mean RTT (ms)")
        ax.legend()
        ax.grid(True, axis="y", alpha=0.3)

    fig.suptitle("Mean RTT: TCP vs UDP — Payload Size × Client Count", fontsize=13)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "combined_latency_bars.png", dpi=150)
    plt.close(fig)
    print("  saved combined_latency_bars.png")


def generate_all_plots():
    ensure_dirs()
    rows = load_all_csvs()
    if not rows:
        print(f"No CSV data found in {RESULTS_DIR}/. Run experiments first.")
        return
    n_files = len(glob.glob(str(RESULTS_DIR / "client_*.csv")))
    print(f"Loaded {len(rows)} rows from {n_files} CSV files.")
    plot_latency_vs_payload(rows)
    plot_throughput_vs_payload(rows)
    plot_wall_vs_payload(rows)
    plot_latency_vs_clients(rows)
    plot_throughput_vs_clients(rows)
    plot_wall_vs_clients(rows)
    plot_combined_bars(rows)
    print(f"All plots saved to {PLOTS_DIR}/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Run TCP/UDP benchmarks and generate plots")
    p.add_argument("--plots-only", action="store_true",
                   help="Skip experiments; only regenerate plots from existing CSVs")
    p.add_argument("--results-dir", type=str, default=None,
                   help="Directory containing result CSVs (default: results/ next to this script)")
    return p.parse_args()


def main():
    global RESULTS_DIR, PLOTS_DIR

    args = parse_args()

    script_dir = Path(__file__).parent

    if args.results_dir:
        RESULTS_DIR = Path(args.results_dir)
    else:
        RESULTS_DIR = script_dir / "results"

    PLOTS_DIR = RESULTS_DIR.parent / "plots"

    if not args.plots_only:
        run_all_experiments()

    generate_all_plots()


if __name__ == "__main__":
    main()