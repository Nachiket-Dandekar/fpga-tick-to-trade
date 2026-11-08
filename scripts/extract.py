import gzip
import struct
import sys
from collections import Counter


def main():
    if len(sys.argv) < 3:
        print("usage: extract.py <src> <dst> [count] [skip]")
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 100_000
    skip = int(sys.argv[4]) if len(sys.argv) > 4 else 0

    opener = gzip.open if src.endswith(".gz") else open
    counts = Counter()
    kept_dir = 0
    with opener(src, "rb") as f, open(dst, "wb") as out:
        first = f.read(3)
        if first != b"\x00\x0c\x53":
            print(f"warning: first bytes are {first.hex(' ')}, expected 00 0c 53")
        f.seek(0)

        for _ in range(skip):
            hdr = f.read(2)
            if len(hdr) < 2:
                break
            body = f.read(struct.unpack(">H", hdr)[0])
            if body[0] == ord("R"):
                out.write(hdr + body)
                kept_dir += 1

        for _ in range(limit):
            hdr = f.read(2)
            if len(hdr) < 2:
                break
            body = f.read(struct.unpack(">H", hdr)[0])
            out.write(hdr + body)
            counts[chr(body[0])] += 1

    if skip:
        print(f"skipped {skip} messages, kept {kept_dir} stock directory (R) messages")
    print(f"wrote {sum(counts.values())} messages to {dst}")
    for t, n in counts.most_common():
        print(f"  {t}: {n}")


if __name__ == "__main__":
    main()
