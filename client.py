#!/usr/bin/env python3
"""
TCP/UDP echo client for benchmarking.
"""

import argparse
import csv
import json
import os
import socket
import threading
import time


def now_wall() -> float:
    return time.time()


def now_mono() -> float:
    return time.monotonic()


def log_event(fp, event: dict):
    fp.write(json.dumps(event, sort_keys=True) + "\n")
    fp.flush()


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes from a TCP socket, looping as needed."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed before all bytes received")
        buf.extend(chunk)
    return bytes(buf)



def tcp_worker(host: str, port: int, payload_bytes: int,
               requests: int, results: list, idx: int):
    """
    One TCP worker: connect → (send → recv) × requests → disconnect.
    Appends one dict per request to results[idx].
    """
    payload = b"x" * payload_bytes

    worker_results = []

    t_connect_start = now_mono()
    wall_connect_start = now_wall()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15.0)
    sock.connect((host, port))
    t_connect_end = now_mono()
    connect_time_s = t_connect_end - t_connect_start

    for req_i in range(requests):
        t_send = now_mono()
        wall_send = now_wall()
        sock.sendall(payload)
        _ = recv_exact(sock, payload_bytes)
        t_recv = now_mono()

        rtt_s = t_recv - t_send
        worker_results.append({
            "proto": "tcp",
            "client_id": idx,
            "request_id": req_i,
            "payload_bytes": payload_bytes,
            "connect_time_s": connect_time_s if req_i == 0 else 0.0,
            "rtt_s": rtt_s,
            "wall_send": wall_send,
        })

    sock.close()
    results[idx] = worker_results


def run_tcp_client(host: str, port: int, log_path: str,
                   payload_bytes: int, requests: int, clients: int) -> None:
    """Run the TCP client benchmark with `clients` concurrent connections."""
    results = [None] * clients
    threads = []

    wall_start = now_wall()
    mono_start = now_mono()

    for i in range(clients):
        t = threading.Thread(
            target=tcp_worker,
            args=(host, port, payload_bytes, requests, results, i),
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    wall_end = now_wall()
    mono_end = now_mono()
    total_wall_s = wall_end - wall_start

    os.makedirs(os.path.dirname(log_path) if os.path.dirname(log_path) else ".", exist_ok=True)
    with open(log_path, "w", newline="") as f:
        fieldnames = ["proto", "client_id", "request_id", "payload_bytes",
                      "connect_time_s", "rtt_s", "wall_send",
                      "clients", "requests_per_client",
                      "total_wall_s", "throughput_MBps"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        total_bytes = clients * requests * payload_bytes * 2  # send + recv
        throughput = total_bytes / total_wall_s / 1e6  # MB/s

        for worker_rows in results:
            if worker_rows is None:
                continue
            for row in worker_rows:
                row["clients"] = clients
                row["requests_per_client"] = requests
                row["total_wall_s"] = round(total_wall_s, 6)
                row["throughput_MBps"] = round(throughput, 6)
                writer.writerow(row)

    print(f"[TCP client] done | clients={clients} payload={payload_bytes}B "
          f"requests={requests} wall={total_wall_s:.3f}s "
          f"throughput={throughput:.3f} MB/s")


def udp_worker(host: str, port: int, payload_bytes: int,
               requests: int, results: list, idx: int):
    """
    One UDP worker: (send → recv) × requests.
    Each worker owns its own socket to avoid recvfrom() races.
    """
    payload = b"x" * payload_bytes

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)   # 5-second timeout per datagram

    worker_results = []
    failures = 0

    for req_i in range(requests):
        t_send = now_mono()
        wall_send = now_wall()
        try:
            sock.sendto(payload, (host, port))
            data, _ = sock.recvfrom(payload_bytes + 128)
            t_recv = now_mono()
            rtt_s = t_recv - t_send
            worker_results.append({
                "proto": "udp",
                "client_id": idx,
                "request_id": req_i,
                "payload_bytes": payload_bytes,
                "connect_time_s": 0.0,
                "rtt_s": rtt_s,
                "wall_send": wall_send,
                "failed": False,
            })
        except socket.timeout:
            failures += 1
            worker_results.append({
                "proto": "udp",
                "client_id": idx,
                "request_id": req_i,
                "payload_bytes": payload_bytes,
                "connect_time_s": 0.0,
                "rtt_s": -1.0,
                "wall_send": wall_send,
                "failed": True,
            })

    sock.close()
    if failures:
        print(f"[UDP worker {idx}] {failures}/{requests} datagrams timed out "
              f"(possible MTU issue at payload={payload_bytes}B)")
    results[idx] = worker_results


def run_udp_client(host: str, port: int, log_path: str,
                   payload_bytes: int, requests: int, clients: int) -> None:
    """Run the UDP client benchmark with `clients` concurrent senders."""
    results = [None] * clients
    threads = []

    wall_start = now_wall()
    mono_start = now_mono()

    for i in range(clients):
        t = threading.Thread(
            target=udp_worker,
            args=(host, port, payload_bytes, requests, results, i),
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    wall_end = now_wall()
    mono_end = now_mono()
    total_wall_s = wall_end - wall_start

    os.makedirs(os.path.dirname(log_path) if os.path.dirname(log_path) else ".", exist_ok=True)
    with open(log_path, "w", newline="") as f:
        fieldnames = ["proto", "client_id", "request_id", "payload_bytes",
                      "connect_time_s", "rtt_s", "wall_send", "failed",
                      "clients", "requests_per_client",
                      "total_wall_s", "throughput_MBps"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        successful = sum(
            1 for w in results if w for r in w if not r.get("failed")
        )
        total_bytes = successful * payload_bytes * 2
        throughput = total_bytes / total_wall_s / 1e6 if total_wall_s > 0 else 0

        for worker_rows in results:
            if worker_rows is None:
                continue
            for row in worker_rows:
                row["clients"] = clients
                row["requests_per_client"] = requests
                row["total_wall_s"] = round(total_wall_s, 6)
                row["throughput_MBps"] = round(throughput, 6)
                writer.writerow(row)

    print(f"[UDP client] done | clients={clients} payload={payload_bytes}B "
          f"requests={requests} wall={total_wall_s:.3f}s "
          f"throughput={throughput:.3f} MB/s")



def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TCP/UDP echo client for benchmarking")
    p.add_argument("--proto", choices=["tcp", "udp"], required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=5001)
    p.add_argument("--payload-bytes", type=int, default=64)
    p.add_argument("--requests", type=int, default=100)
    p.add_argument("--clients", type=int, default=1)
    p.add_argument("--log", required=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.proto == "tcp":
        run_tcp_client(args.host, args.port, args.log,
                       args.payload_bytes, args.requests, args.clients)
    else:
        run_udp_client(args.host, args.port, args.log,
                       args.payload_bytes, args.requests, args.clients)


if __name__ == "__main__":
    main()