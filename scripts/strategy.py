import struct
import sys

from book import Book, read_messages, setup

DEFAULT_LIMIT_PRICE = 0xFFFFFFFF
DEFAULT_MAX_QTY = 500
DEFAULT_STOCK = "UN      "


class Strategy:
    def __init__(self, limit_price=DEFAULT_LIMIT_PRICE, max_qty=DEFAULT_MAX_QTY):
        self.limit_price = limit_price
        self.max_qty = max_qty
        self.prev_valid = 0
        self.prev_price = 0
        self.orders = []

    def reset(self):
        self.prev_valid = 0
        self.prev_price = 0
        self.orders = []

    def step(self, ask_valid, ask_price, ask_qty, msg_index=0):
        fired = None
        if ask_valid and (not self.prev_valid or ask_price != self.prev_price):
            if ask_price <= self.limit_price:
                shares = min(ask_qty, self.max_qty)
                order_num = len(self.orders) + 1
                fired = {
                    "order_num": order_num,
                    "token": f"T2T000{order_num:08X}",
                    "shares": shares,
                    "price": ask_price,
                    "msg_index": msg_index,
                }
                self.orders.append(fired)
        self.prev_valid = 1 if ask_valid else 0
        self.prev_price = ask_price
        return fired


def run_strategy(bodies, locate, base, limit_price=DEFAULT_LIMIT_PRICE, max_qty=DEFAULT_MAX_QTY):
    book = Book(locate, base)
    strat = Strategy(limit_price, max_qty)
    for idx, body in enumerate(bodies, 1):
        snap = book.process(body)
        if snap is not None:
            _, _, _, av, ap, aq = snap
            strat.step(av, ap, aq, idx)
    return book, strat.orders


def pack_order_payload(order_num, shares, price, latency, msg_index, stock=DEFAULT_STOCK):
    if isinstance(stock, int):
        stock_bytes = stock.to_bytes(8, "big")
    elif isinstance(stock, bytes):
        stock_bytes = stock.ljust(8, b" ")[:8]
    else:
        stock_bytes = stock.ljust(8)[:8].encode("ascii")
    token = f"T2T000{order_num:08X}".encode("ascii")
    return struct.pack(
        ">c14scI8sII4scccIccII",
        b"O",
        token,
        b"B",
        shares,
        stock_bytes,
        price,
        0,
        b"T2T ",
        b"N",
        b"P",
        b"N",
        0,
        b"N",
        b"N",
        latency,
        msg_index,
    )


def unpack_order_payload(payload):
    assert len(payload) == 57, f"expected 57-byte payload, got {len(payload)}"
    (msg_type, token, side, shares, stock, price, tif, firm,
     display, capacity, iso, min_qty, cross, cust, latency, msg_index) = struct.unpack(
        ">c14scI8sII4scccIccII", payload
    )
    return {
        "type": msg_type.decode("ascii", errors="replace"),
        "token": token.decode("ascii", errors="replace"),
        "order_num": int(token[6:].decode("ascii"), 16),
        "side": side.decode("ascii", errors="replace"),
        "shares": shares,
        "stock": stock.decode("ascii", errors="replace"),
        "price": price,
        "tif": tif,
        "firm": firm.decode("ascii", errors="replace"),
        "display": display.decode("ascii", errors="replace"),
        "capacity": capacity.decode("ascii", errors="replace"),
        "iso": iso.decode("ascii", errors="replace"),
        "min_qty": min_qty,
        "cross": cross.decode("ascii", errors="replace"),
        "customer": cust.decode("ascii", errors="replace"),
        "latency": latency,
        "msg_index": msg_index,
    }


def main():
    if len(sys.argv) < 2:
        print("usage: strategy.py <itch file> [ticker] [limit]")
        sys.exit(1)
    path = sys.argv[1]
    ticker = sys.argv[2] if len(sys.argv) > 2 else None
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    ticker, locate, base = setup(path, ticker)
    bodies = []
    for body in read_messages(path):
        if limit is not None and len(bodies) >= limit:
            break
        bodies.append(body)
    _, orders = run_strategy(bodies, locate, base)
    print(f"{ticker}: {len(orders)} orders from {len(bodies)} messages")
    for o in orders[:5]:
        print(f"  {o['token']} {o['shares']} @ ${o['price'] / 10000:.2f} (msg {o['msg_index']})")


if __name__ == "__main__":
    main()
