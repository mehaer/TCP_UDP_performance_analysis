#!/usr/bin/env python3
"""
TCP/UDP echo server for benchmarking.
"""

import argparse
import json
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

def handle_tcp_client(conn: socket.socket, addr, payload_bytes: int,
                      requests: int, log_fp, lock: threading.Lock):
    """Handle one TCP client connection: receive `requests` echoes."""
    try:
        for _ in range(requests):
            data = recv_exact(conn, payload_bytes)
            conn.sendall(data)             
            event = {
                "proto": "tcp",
                "event": "echo",
                "client": str(addr),
                "payload_bytes": len(data),
                "wall": now_wall(),
            }
            with lock:
                log_event(log_fp, event)
    except Exception as e:
        print(f"[TCP server] error with {addr}: {e}")
    finally:
        conn.close()


def run_tcp_server(bind: str, port: int, log_path: str,
                   payload_bytes: int, requests: int, clients: int) -> None:
    """Run the TCP server benchmark."""
    with open(log_path, "a") as log_fp:
        lock = threading.Lock()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        srv.bind((bind, port))
        # Backlog large enough for the expected concurrency
        srv.listen(min(clients + 32, 4096))
        print(f"[TCP server] listening on {bind}:{port}, "
              f"payload={payload_bytes}B, requests/conn={requests}, "
              f"expected_clients={clients}")

        threads = []
        # Accept exactly `clients` connections
        for _ in range(clients):
            conn, addr = srv.accept()
            t = threading.Thread(
                target=handle_tcp_client,
                args=(conn, addr, payload_bytes, requests, log_fp, lock),
                daemon=True,
            )
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        srv.close()
        print("[TCP server] done")



def run_udp_server(bind: str, port: int, log_path: str,
                   payload_bytes: int, requests: int, clients: int) -> None:
    """Run the UDP server benchmark."""
    total_expected = clients * requests
    received = 0

    # Enlarge kernel buffers to absorb bursts from many concurrent senders
    buf_size = 4 * 1024 * 1024  # 4 MB

    with open(log_path, "a") as log_fp:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buf_size)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buf_size)
        sock.bind((bind, port))
        print(f"[UDP server] listening on {bind}:{port}, "
              f"payload={payload_bytes}B, total_datagrams={total_expected}")

        while received < total_expected:
            # Buffer slightly larger than payload to detect oversized sends
            data, addr = sock.recvfrom(payload_bytes + 128)
            sock.sendto(data, addr)        # echo back
            received += 1
            event = {
                "proto": "udp",
                "event": "echo",
                "client": str(addr),
                "payload_bytes": len(data),
                "wall": now_wall(),
            }
            log_event(log_fp, event)

        sock.close()
        print(f"[UDP server] done after {received} datagrams")



def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TCP/UDP echo server for benchmarking")
    p.add_argument("--proto", choices=["tcp", "udp"], required=True)
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5001)
    p.add_argument("--payload-bytes", type=int, default=64)
    p.add_argument("--requests", type=int, default=100)
    p.add_argument("--clients", type=int, default=1)
    p.add_argument("--log", required=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.proto == "tcp":
        run_tcp_server(args.bind, args.port, args.log,
                       args.payload_bytes, args.requests, args.clients)
    else:
        run_udp_server(args.bind, args.port, args.log,
                       args.payload_bytes, args.requests, args.clients)


if __name__ == "__main__":
    main()