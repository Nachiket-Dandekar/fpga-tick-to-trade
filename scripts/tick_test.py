import argparse
import csv
import math
import socket
import statistics
import struct
import threading
import time

from book import read_messages, setup
from replay import limited, mold_packets
from strategy import DEFAULT_LIMIT_PRICE, DEFAULT_MAX_QTY, run_strategy, unpack_order_payload

ORDER_PORT = 26401
RCVBUF_BYTES = 4 * 1024 * 1024


def percentile(sorted_vals, pct):
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, math.ceil(pct / 100.0 * len(sorted_vals)) - 1))
    return float(sorted_vals[idx])


def compare_orders(received_raw, expected_orders, expected_stock):
    parsed = []
    mismatches = abs(len(received_raw) - len(expected_orders))
    stock_padded = expected_stock.ljust(8)[:8]

    for i, pkt in enumerate(received_raw):
        if len(pkt) != 57:
            mismatches += 1
            continue
        order = unpack_order_payload(pkt)
        parsed.append(order)
        if i < len(expected_orders):
            exp = expected_orders[i]
            ok = (
                order["type"] == "O"
                and order["side"] == "B"
                and order["token"] == exp["token"]
                and order["shares"] == exp["shares"]
                and order["price"] == exp["price"]
                and order["stock"] == stock_padded
                and order["msg_index"] == exp["msg_index"]
            )
            if not ok:
                mismatches += 1

    return parsed, mismatches


def write_latency_csv(path, orders):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["order_number", "message_index", "price", "shares", "latency_cycles"])
        for o in orders:
            writer.writerow([o["order_num"], o["msg_index"], o["price"], o["shares"], o["latency"]])


def main():
    parser = argparse.ArgumentParser(description="Replay ITCH data and verify returned OUCH orders")
    parser.add_argument("file")
    parser.add_argument("--host", default="255.255.255.255")
    parser.add_argument("--port", type=int, default=26400)
    parser.add_argument("--order-port", type=int, default=ORDER_PORT)
    parser.add_argument("--iface", default="", help="local address to bind to")
    parser.add_argument("--device", default="", help="network device to send from, such as eth0")
    parser.add_argument("--limit", type=int, default=None, help="number of messages to send")
    parser.add_argument("--gap", type=float, default=0.0, help="seconds between packets")
    parser.add_argument("--session", default="T2TREPLAY ")
    parser.add_argument("--stock", default=None, help="ticker, default is the busiest one")
    parser.add_argument("--limit-price", type=lambda x: int(x, 0), default=DEFAULT_LIMIT_PRICE)
    parser.add_argument("--max-qty", type=int, default=DEFAULT_MAX_QTY)
    parser.add_argument("--clock-mhz", type=float, default=100.0)
    parser.add_argument("--csv", default="latency.csv")
    args = parser.parse_args()

    ticker, locate, base = setup(args.file, args.stock)
    bodies = list(limited(read_messages(args.file), args.limit))
    _, expected_orders = run_strategy(bodies, locate, base, args.limit_price, args.max_qty)

    rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RCVBUF_BYTES)
    except OSError:
        pass
    if args.device:
        rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, args.device.encode())
    rx_sock.bind((args.iface, args.order_port))
    rx_sock.settimeout(0.1)

    received_raw = []
    stop_event = threading.Event()

    def recv_loop():
        while not stop_event.is_set():
            try:
                data, _ = rx_sock.recvfrom(2048)
                received_raw.append(data)
            except socket.timeout:
                continue
            except OSError:
                break

    rx_thread = threading.Thread(target=recv_loop, daemon=True)
    rx_thread.start()

    session = args.session.encode().ljust(10)[:10]
    tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if args.device:
        tx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, args.device.encode())
    tx_sock.bind((args.iface, 0))

    packets = 0
    messages = 0
    start = time.time()
    for payload in mold_packets(bodies, session):
        tx_sock.sendto(payload, (args.host, args.port))
        packets += 1
        messages += struct.unpack(">H", payload[18:20])[0]
        if args.gap:
            time.sleep(args.gap)
    tx_sock.close()
    elapsed = time.time() - start

    time.sleep(1.0)
    stop_event.set()
    rx_thread.join(timeout=1.0)
    rx_sock.close()

    parsed, mismatches = compare_orders(received_raw, expected_orders, ticker)
    write_latency_csv(args.csv, parsed)

    print(f"sent {packets} packets, {messages} messages in {elapsed:.1f} s")
    print(f"orders expected: {len(expected_orders)}, received: {len(parsed)}, mismatches: {mismatches}")

    if parsed:
        lats = sorted(o["latency"] for o in parsed)
        ns_per_cycle = 1000.0 / args.clock_mhz
        l_min = lats[0]
        l_med = statistics.median(lats)
        l_p99 = percentile(lats, 99)
        l_max = lats[-1]
        print(
            f"latency cycles: min={l_min} median={l_med:.1f} p99={l_p99:.1f} max={l_max}"
        )
        print(
            f"latency ns ({args.clock_mhz:g} MHz): "
            f"min={l_min * ns_per_cycle:.1f} median={l_med * ns_per_cycle:.1f} "
            f"p99={l_p99 * ns_per_cycle:.1f} max={l_max * ns_per_cycle:.1f}"
        )


if __name__ == "__main__":
    main()
