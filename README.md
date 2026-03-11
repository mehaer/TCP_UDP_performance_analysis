# TCP vs UDP Performance Benchmark
**CS 417 — Assignment 1**

A client/server benchmarking framework that measures and compares the performance of TCP and UDP across varying payload sizes and concurrency levels.

---

## Project Structure

```
tcp_udp_benchmark/
├── client.py            # TCP/UDP echo client
├── server.py            # TCP/UDP echo server
├── run_experiments.py   # Experiment runner and plot generator
├── run_benchmark.sh     # Full two-machine orchestration script
├── results/             # Raw CSV and JSONL output (generated)
├── plots/               # PNG graphs (generated)
└── README.md
```

---

## Requirements

### Local machine (Mac/Linux)
- `expect` — for SSH automation (`brew install expect` on macOS)
- Python 3.8+
- `matplotlib`, `numpy` — for plot generation (`conda install matplotlib numpy`)

### Remote machines (iLab)
- Python 3.8+ (available by default on iLab)
- Two iLab machines with network connectivity

---

## Quick Start

### 1. Set up your password file
```bash
echo "YourILabPassword" > ~/.ilab_pass
chmod 600 ~/.ilab_pass
```

### 2. Run the full benchmark
```bash
./run_benchmark.sh <server_host> <client_host> <netid> <password_file>
```

**Example:**
```bash
./run_benchmark.sh grep.cs.rutgers.edu kill.cs.rutgers.edu mdc265 ~/.ilab_pass
```

This will:
1. Copy all benchmark files to both iLab machines
2. Run every combination of protocol × payload × client count
3. Download all result CSVs to your local `results/` folder
4. Generate plots into your local `plots/` folder

### 3. If plots were not auto-generated
If `matplotlib` is not available locally, generate plots manually after the benchmark completes:
```bash
python3 run_experiments.py --plots-only --results-dir results/
```

---

## Experiment Parameters

| Parameter | Values |
|---|---|
| Protocols | TCP, UDP |
| Payload sizes | 64B, 512B, 1KB, 4KB, 8KB |
| Concurrent clients | 1, 10, 100, 1000 |
| Requests per client | 100 |
| TCP port | 5101 |
| UDP port | 5102 |

---

## Running Locally (Single Machine)

To run experiments on a single machine via loopback (useful for testing):
```bash
python3 run_experiments.py
```

This starts server and client subprocesses locally on `127.0.0.1` and saves results to `results/` and plots to `plots/`.

---

## Manual Usage

### Server
```bash
python3 server.py --proto tcp --bind 0.0.0.0 --port 5101 \
    --payload-bytes 512 --requests 100 --clients 10 --log results/server.jsonl
```

### Client
```bash
python3 client.py --proto tcp --host <server_ip> --port 5101 \
    --payload-bytes 512 --requests 100 --clients 10 --log results/client.csv
```

### Supported flags (both client and server)

| Flag | Description |
|---|---|
| `--proto` | `tcp` or `udp` |
| `--port` | Port number (default: 5001) |
| `--payload-bytes` | Payload size in bytes (default: 64) |
| `--requests` | Requests per client (default: 100) |
| `--clients` | Number of concurrent clients (default: 1) |
| `--log` | Path to output log file (CSV for client, JSONL for server) |
| `--host` | *(client only)* Server hostname or IP |
| `--bind` | *(server only)* Bind address (default: 0.0.0.0) |

---

## Output Format

### Client logs (`results/client_<proto>_p<payload>_c<clients>.csv`)
Each row represents one request:

| Column | Description |
|---|---|
| `proto` | `tcp` or `udp` |
| `client_id` | Worker thread index |
| `request_id` | Request index within the worker |
| `payload_bytes` | Payload size in bytes |
| `rtt_s` | Round-trip time in seconds (`-1.0` if failed/dropped) |
| `connect_time_s` | TCP connection setup time (first request only; 0 for UDP) |
| `wall_send` | Wall clock time at send |
| `total_wall_s` | Total elapsed time for the entire experiment |
| `throughput_MBps` | Throughput in MB/s for the entire experiment |
| `failed` | `True` if the request timed out (UDP only) |

### Server logs (`results/server_<proto>_p<payload>_c<clients>.jsonl`)
One JSON line per echoed message, recording protocol, client address, payload size, and wall time.

---

## Generated Plots

| Plot | Description |
|---|---|
| `latency_vs_payload.png` | Mean RTT vs payload size (1 client) |
| `throughput_vs_payload.png` | Throughput vs payload size (1 client) |
| `wall_vs_payload.png` | Total time vs payload size (1 client) |
| `latency_vs_clients.png` | Mean RTT vs number of clients (512B payload) |
| `throughput_vs_clients.png` | Throughput vs number of clients (512B payload) |
| `wall_vs_clients.png` | Total time vs number of clients (512B payload) |
| `combined_latency_bars.png` | Mean RTT grouped by payload size and client count |

---

## Experimental Setup

- **Server machine:** `grep.cs.rutgers.edu`
- **Client machine:** `kill.cs.rutgers.edu`
- **Network:** Rutgers iLab internal network
- **OS:** Ubuntu 24 (iLab)
- **Python:** 3.12

---

## Notes

- iLab home directories are NFS-shared across all machines, so files written on `grep` are immediately visible on `kill` and vice versa.
- The server is launched with `nohup` so it survives the SSH session closing.
- UDP packet loss is recorded in the CSV as `failed=True` with `rtt_s=-1.0` and is excluded from RTT/throughput calculations.
- If you hit system socket limits at `clients=1000`, reduce `CLIENT_COUNTS` in `run_benchmark.sh` and document the limit in your report.
