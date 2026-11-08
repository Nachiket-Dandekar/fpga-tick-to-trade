import struct

LENGTHS = {"A": 36, "F": 40, "E": 31, "C": 36, "X": 23, "D": 19, "U": 35,
           "S": 12, "R": 39, "P": 44, "Q": 40, "I": 50}


def header(t, locate, tracking=0, ts=0):
    return struct.pack(">cHH", t.encode(), locate, tracking) + ts.to_bytes(6, "big")


def add_order(ref, side, shares, stock, price, locate=1, attributed=False):
    body = header("F" if attributed else "A", locate)
    body += struct.pack(">Qc I8s I", ref, side.encode(), shares,
                        stock.ljust(8).encode(), price)
    if attributed:
        body += b"MPID"
    return body


def executed(ref, shares, locate=1, match=0):
    return header("E", locate) + struct.pack(">QIQ", ref, shares, match)


def executed_price(ref, shares, price, locate=1, match=0):
    return header("C", locate) + struct.pack(">QIQcI", ref, shares, match, b"Y", price)


def cancel(ref, shares, locate=1):
    return header("X", locate) + struct.pack(">QI", ref, shares)


def delete(ref, locate=1):
    return header("D", locate) + struct.pack(">Q", ref)


def replace(old_ref, new_ref, shares, price, locate=1):
    return header("U", locate) + struct.pack(">QQII", old_ref, new_ref, shares, price)


def random_message(rng):
    t = rng.choice(list(LENGTHS))
    body = bytearray(rng.getrandbits(8) for _ in range(LENGTHS[t]))
    body[0] = ord(t)
    if t in "AF":
        body[19] = ord(rng.choice("BS"))
    return bytes(body)


def frame(bodies):
    return b"".join(struct.pack(">H", len(b)) + b for b in bodies)


def read_itch_file(path, limit=None):
    bodies = []
    with open(path, "rb") as f:
        while limit is None or len(bodies) < limit:
            hdr = f.read(2)
            if len(hdr) < 2:
                break
            bodies.append(f.read(struct.unpack(">H", hdr)[0]))
    return bodies


def val(sig):
    v = sig.value
    return v.to_unsigned() if hasattr(v, "to_unsigned") else int(v)
