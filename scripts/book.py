import struct
import sys
from collections import Counter

SET_BITS = 10
WAYS = 4
LEVEL_BITS = 12
SETS = 1 << SET_BITS
LEVELS = 1 << LEVEL_BITS
TICK = 100

BUY, SELL = 1, 0


def be(body, start, n):
    return int.from_bytes(body[start:start + n], "big")


def set_index(ref):
    return (ref ^ (ref >> SET_BITS)) % SETS


def pick_base(price):
    return max(0, (price // TICK - LEVELS // 2) * TICK)


class Book:
    def __init__(self, locate, base):
        self.locate = locate
        self.base = base
        self.sets = [[None] * WAYS for _ in range(SETS)]
        self.levels = {BUY: [0] * LEVELS, SELL: [0] * LEVELS}
        self.collisions = 0
        self.out_of_range = 0

    def level_of(self, price):
        if price < self.base:
            return None
        lvl = (price - self.base) // TICK
        return lvl if lvl < LEVELS else None

    def add(self, ref, side, shares, price):
        if shares == 0:
            return
        lvl = self.level_of(price)
        if lvl is None:
            self.out_of_range += 1
            return
        ways = self.sets[set_index(ref)]
        if None not in ways:
            self.collisions += 1
            return
        ways[ways.index(None)] = [ref, side, lvl, shares]
        self.levels[side][lvl] += shares

    def reduce(self, ref, shares=None):
        ways = self.sets[set_index(ref)]
        way = next((w for w, e in enumerate(ways) if e and e[0] == ref), None)
        if way is None:
            return None
        entry = ways[way]
        _, side, lvl, left = entry
        dec = left if shares is None else min(shares, left)
        entry[3] -= dec
        if entry[3] == 0:
            ways[way] = None
        self.levels[side][lvl] -= dec
        return side

    def best(self):
        bids, asks = self.levels[BUY], self.levels[SELL]
        bid = next((i for i in range(LEVELS - 1, -1, -1) if bids[i]), None)
        ask = next((i for i in range(LEVELS) if asks[i]), None)
        out = []
        for lvl, side in ((bid, bids), (ask, asks)):
            if lvl is None:
                out += [0, 0, 0]
            else:
                out += [1, self.base + lvl * TICK, side[lvl]]
        return tuple(out)

    def process(self, body):
        t = chr(body[0])
        if t not in "AFECXDU" or be(body, 1, 2) != self.locate:
            return None
        ref = be(body, 11, 8)
        if t in "AF":
            side = BUY if body[19] == ord("B") else SELL
            self.add(ref, side, be(body, 20, 4), be(body, 32, 4))
        elif t in "ECX":
            self.reduce(ref, be(body, 19, 4))
        elif t == "D":
            self.reduce(ref)
        elif t == "U":
            side = self.reduce(ref)
            if side is not None:
                self.add(be(body, 19, 8), side, be(body, 27, 4), be(body, 31, 4))
        return self.best()


def read_messages(path):
    with open(path, "rb") as f:
        while True:
            hdr = f.read(2)
            if len(hdr) < 2:
                return
            yield f.read(struct.unpack(">H", hdr)[0])


def directory(path):
    names = {}
    for body in read_messages(path):
        if body[0] == ord("R"):
            names[body[11:19].decode().strip()] = be(body, 1, 2)
    return names


def busiest(path):
    counts = Counter()
    for body in read_messages(path):
        if chr(body[0]) in "AFECXDU":
            counts[be(body, 1, 2)] += 1
    return counts


def first_add_price(path, locate):
    for body in read_messages(path):
        if chr(body[0]) in "AF" and be(body, 1, 2) == locate:
            return be(body, 32, 4)
    return None


def setup(path, ticker=None):
    names = directory(path)
    tickers = {v: k for k, v in names.items()}
    if ticker:
        locate = names[ticker]
    else:
        locate = busiest(path).most_common(1)[0][0]
        ticker = tickers.get(locate, "?")
    base = pick_base(first_add_price(path, locate))
    return ticker, locate, base


def main():
    if len(sys.argv) < 2:
        print("usage: book.py <itch file> [ticker]")
        sys.exit(1)
    path = sys.argv[1]
    ticker, locate, base = setup(path, sys.argv[2] if len(sys.argv) > 2 else None)
    book = Book(locate, base)
    updates = 0
    snap = None
    for body in read_messages(path):
        s = book.process(body)
        if s is not None:
            updates += 1
            snap = s

    print(f"{ticker}: locate {locate}, base ${base / 10000:.2f}, "
          f"window ${base / 10000:.2f} to ${(base + (LEVELS - 1) * TICK) / 10000:.2f}")
    print(f"messages for {ticker}: {updates}")
    print(f"open orders at end: {sum(e is not None for ways in book.sets for e in ways)}")
    print(f"collisions: {book.collisions}  out of range: {book.out_of_range}")
    if snap:
        bv, bp, bq, av, ap, aq = snap
        print("best bid: " + (f"{bq} @ ${bp / 10000:.2f}" if bv else "none"))
        print("best ask: " + (f"{aq} @ ${ap / 10000:.2f}" if av else "none"))


if __name__ == "__main__":
    main()
