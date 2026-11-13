import argparse
import socket
import struct
import time

from book import read_messages

MAX_PAYLOAD = 1400
HEADER_LEN = 20


def mold_packets(bodies, session=b"T2TREPLAY ", first_seq=1, max_payload=MAX_PAYLOAD):
    assert len(session) == 10
    seq = first_seq
    blocks = []
    size = HEADER_LEN
    for body in bodies:
        block = struct.pack(">H", len(body)) + body
        if blocks and size + len(block) > max_payload:
            yield session + struct.pack(">QH", seq, len(blocks)) + b"".join(blocks)
            seq += len(blocks)
            blocks = []
            size = HEADER_LEN
        blocks.append(block)
        size += len(block)
    if blocks:
        yield session + struct.pack(">QH", seq, len(blocks)) + b"".join(blocks)


def limited(bodies, limit):
    for i, body in enumerate(bodies):
        if limit is not None and i >= limit:
            return
        yield body


def main():
    parser = argparse.ArgumentParser(description="Replay an ITCH file as MoldUDP64 over UDP broadcast")
    parser.add_argument("file")
    parser.add_argument("--host", default="255.255.255.255")
    parser.add_argument("--port", type=int, default=26400)
    parser.add_argument("--iface", default="", help="local address to bind to")
    parser.add_argument("--device", default="", help="network device to send from, such as eth0")
    parser.add_argument("--limit", type=int, default=None, help="number of messages to send")
    parser.add_argument("--gap", type=float, default=0.0, help="seconds between packets")
    parser.add_argument("--session", default="T2TREPLAY ")
    args = parser.parse_args()

    session = args.session.encode().ljust(10)[:10]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if args.device:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, args.device.encode())
    sock.bind((args.iface, 0))

    packets = 0
    messages = 0
    start = time.time()
    for payload in mold_packets(limited(read_messages(args.file), args.limit), session):
        sock.sendto(payload, (args.host, args.port))
        packets += 1
        messages += struct.unpack(">H", payload[18:20])[0]
        if args.gap:
            time.sleep(args.gap)
    sock.close()

    print(f"sent {packets} packets, {messages} messages in {time.time() - start:.1f} s")


if __name__ == "__main__":
    main()
