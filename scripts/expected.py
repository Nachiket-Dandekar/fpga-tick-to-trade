import argparse

from book import Book, read_messages, setup
from replay import limited, mold_packets


def expected_fields(bodies, locate, base):
    book = Book(locate, base)
    count = 0
    for body in bodies:
        book.process(body)
        count += 1
    bv, bp, bq, av, ap, aq = book.best()
    return {"msg": count, "col": book.collisions, "oor": book.out_of_range,
            "bid": (bv, bp, bq), "ask": (av, ap, aq)}


def status_text(fields):
    bv, bp, bq = fields["bid"]
    av, ap, aq = fields["ask"]
    return (f"msg={fields['msg']:08X} col={fields['col']:04X} oor={fields['oor']:04X} "
            f"bid={bv} {bp:08X} {bq:08X} ask={av} {ap:08X} {aq:08X}")


def dollars(side):
    valid, price, qty = side
    return f"{qty} @ ${price / 10000:.2f}" if valid else "none"


def main():
    parser = argparse.ArgumentParser(description="Show what the board should print after a replay")
    parser.add_argument("file")
    parser.add_argument("--limit", type=int, default=None, help="number of messages sent by replay.py")
    parser.add_argument("--stock", default=None, help="ticker, default is the busiest one")
    args = parser.parse_args()

    ticker, locate, base = setup(args.file, args.stock)
    bodies = list(limited(read_messages(args.file), args.limit))
    packets = sum(1 for _ in mold_packets(bodies))
    fields = expected_fields(bodies, locate, base)

    print(f"{ticker}: TARGET_LOCATE {locate} (0x{locate:04X}), BASE_PRICE {base} (0x{base:08X})")
    print(f"replay sends {packets} packets ({len(bodies)} messages)")
    print("ok= and drop= also count other traffic on the wire, such as ARP")
    print("crc=00000000 gap=00000000 ovf=00000000 if nothing was lost")
    print(status_text(fields))
    print(f"best bid {dollars(fields['bid'])}, best ask {dollars(fields['ask'])}")


if __name__ == "__main__":
    main()
