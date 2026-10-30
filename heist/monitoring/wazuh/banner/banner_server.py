#!/usr/bin/env python3
import socket
import threading
import time
import argparse

BIND_IP = "::"  # IPv6 any (use "::1" for IPv6 loopback only)
DEFAULT_PORT = 15150
BANNER = (
    "********************************************************\n"
    "NOTICE: Management service. DO NOT ATTACK OR EXPLOIT.\n"
    "Violations may lead to disqualification. Contact: ctf-admin@example.com\n"
    "********************************************************\n"
).encode("utf-8")


def handle(conn, addr):
    try:
        conn.sendall(BANNER)
        try:
            conn.shutdown(socket.SHUT_WR)
        except Exception:
            pass
        time.sleep(0.05)
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def listen_on_port(port):
    """Create and run a listener on a specific port."""
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    except Exception:
        pass

    s.bind((BIND_IP, port))
    s.listen(50)
    print(f"Banner server listening on [{BIND_IP}]:{port} (IPv6)")

    while True:
        conn, addr = s.accept()
        t = threading.Thread(target=handle, args=(conn, addr), daemon=True)
        t.start()


def main():
    parser = argparse.ArgumentParser(
        description="Simple IPv4/IPv6 banner server."
    )
    parser.add_argument(
        "--port",
        type=int,
        nargs='+',
        default=[DEFAULT_PORT],
        help=f"Port(s) to bind (default: {DEFAULT_PORT}). Can specify multiple ports.",
    )
    args = parser.parse_args()
    ports = args.port

    # Create a thread for each port
    threads = []
    for port in ports:
        t = threading.Thread(target=listen_on_port, args=(port,), daemon=True)
        t.start()
        threads.append(t)

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()