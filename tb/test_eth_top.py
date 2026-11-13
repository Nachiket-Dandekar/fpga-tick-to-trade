import os
import random
import struct
import sys
import time

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, ClockCycles, Timer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import book as model
from replay import mold_packets
from eth_frames import MiiDriver, udp_frame, with_fcs
from itch_msgs import add_order, delete, read_itch_file, val
from test_order_book import random_flow, snapshot, fmt, P

COUNTERS = ["frames_ok", "crc_errors", "frames_dropped", "seq_gaps",
            "fifo_overflows", "msg_count", "fifo_max"]
CLEAR_CYCLES = 8200
UDP_HEADERS = 42


async def start(dut, locate, base):
    cocotb.start_soon(Clock(dut.rx_clk, 40, unit="ns").start())
    await Timer(13.7, unit="ns")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    mii = MiiDriver(dut, clk=dut.rx_clk)
    dut.target_locate.value = locate
    dut.base_price.value = base
    dut.rst.value = 1
    await ClockCycles(dut.clk, 20)
    dut.rst.value = 0
    await ClockCycles(dut.clk, CLEAR_CYCLES)
    return mii


async def book_monitor(dut, results):
    while True:
        await RisingEdge(dut.book_update)
        await ReadOnly()
        results.append(snapshot(dut))


async def drain(dut):
    for _ in range(1000):
        await ClockCycles(dut.clk, 100)
        if (val(dut.rx_cross.empty) and not val(dut.fifo.level) and not val(dut.fifo.out_valid)
                and not val(dut.book.busy)):
            break
    await ClockCycles(dut.clk, 20)


def counters(dut):
    return {c: val(getattr(dut, c)) for c in COUNTERS}


def frames_for(bodies):
    return [bytearray(with_fcs(udp_frame(p))) for p in mold_packets(bodies)]


async def run_eth(dut, mii, frames, applied, locate, base, name):
    ref = model.Book(locate, base)
    expected = [s for s in (ref.process(b) for b in applied) if s is not None]

    results = []
    mon = cocotb.start_soon(book_monitor(dut, results))
    t0 = time.time()
    for frame in frames:
        await mii.send(bytes(frame))
    await drain(dut)
    mon.cancel()

    assert len(results) == len(expected), \
        f"{name}: expected {len(expected)} book updates, got {len(results)}"
    for i, (got, exp) in enumerate(zip(results, expected)):
        assert got == exp, f"{name}: update {i}: got {fmt(got)}, expected {fmt(exp)}"
    assert val(dut.collisions) == ref.collisions, \
        f"{name}: collisions {val(dut.collisions)}, expected {ref.collisions}"
    assert val(dut.out_of_range) == ref.out_of_range, \
        f"{name}: out_of_range {val(dut.out_of_range)}, expected {ref.out_of_range}"

    c = counters(dut)
    dut._log.info(f"{name}: " + ", ".join(f"{k} {v}" for k, v in c.items()))
    assert c["msg_count"] == len(applied), \
        f"{name}: msg_count {c['msg_count']}, expected {len(applied)}"
    dut._log.info(f"{name}: {len(applied)} messages in {len(frames)} frames, "
                  f"{len(expected)} book updates matched, collisions {ref.collisions}, "
                  f"out of range {ref.out_of_range}, {time.time() - t0:.0f} s")
    return c


def check_clean(c, frames):
    assert c["frames_ok"] == len(frames), f"frames_ok {c['frames_ok']}, expected {len(frames)}"
    assert c["crc_errors"] == 0 and c["frames_dropped"] == 0 and c["seq_gaps"] == 0, str(c)
    assert c["fifo_overflows"] == 0, f"fifo overflowed {c['fifo_overflows']} times"


@cocotb.test()
async def test_random_flow_over_ethernet(dut):
    base = model.pick_base(P(20.00))
    mii = await start(dut, 7, base)
    bodies = random_flow(random.Random(11), 6000)
    frames = frames_for(bodies)
    c = await run_eth(dut, mii, frames, bodies, 7, base, "random flow")
    check_clean(c, frames)


@cocotb.test()
async def test_long_scan_stall(dut):
    locate, other = 7, 8
    top = (model.LEVELS - 1) * model.TICK
    mii = await start(dut, locate, 0)
    rng = random.Random(14)
    ref = 1000

    def filler(n):
        nonlocal ref
        out = []
        for _ in range(n):
            out.append(add_order(ref, rng.choice("BS"), rng.randint(1, 500), "OTHER",
                                 P(20.00) + 100 * rng.randint(-30, 30), other))
            ref += 4
        return out

    bodies = [add_order(1, "B", 100, "LOW", model.TICK, locate)]
    bodies += filler(50)
    for gap in [150, 120, 110, 0, 150]:
        bodies += [add_order(ref, "B", 10, "TOP", top, locate), delete(ref, locate)]
        ref += 4
        bodies += filler(gap)
    bodies += filler(400)

    frames = frames_for(bodies)
    c = await run_eth(dut, mii, frames, bodies, locate, 0, "long scan stall")
    check_clean(c, frames)
    dut._log.info(f"long scan stall: fifo_max {c['fifo_max']} of {1 << int(dut.FIFO_ADDR.value)}")


@cocotb.test(skip=not os.environ.get("ITCH_FILE"))
async def test_real_data_over_ethernet(dut):
    path = os.environ["ITCH_FILE"]
    limit = int(os.environ.get("ETH_LIMIT", "100000"))
    ticker, locate, base = model.setup(path, os.environ.get("STOCK"))
    bodies = [b for b in read_itch_file(path) if b[0] != ord("R")]
    if limit > 0:
        bodies = bodies[:limit]
    mii = await start(dut, locate, base)
    frames = frames_for(bodies)
    c = await run_eth(dut, mii, frames, bodies, locate, base, f"{ticker} over ethernet")
    check_clean(c, frames)


def message_offsets(payload):
    offsets = []
    pos = 20
    while pos < len(payload):
        offsets.append(pos)
        pos += 2 + struct.unpack(">H", payload[pos:pos + 2])[0]
    return offsets


@cocotb.test()
async def test_corrupted_frames(dut):
    base = model.pick_base(P(20.00))
    mii = await start(dut, 7, base)
    bodies = random_flow(random.Random(13), 4000)
    payloads = list(mold_packets(bodies))
    frames = [bytearray(with_fcs(udp_frame(p))) for p in payloads]
    counts = [struct.unpack(">H", p[18:20])[0] for p in payloads]
    first = [sum(counts[:i]) for i in range(len(payloads))]

    bad_len = len(payloads) // 3
    lost_from = 2
    frames[bad_len][UDP_HEADERS + message_offsets(payloads[bad_len])[lost_from]] |= 0x80

    bad_port = 2 * len(payloads) // 3
    frames[bad_port][37] ^= 0x01

    lost = set(range(first[bad_len] + lost_from, first[bad_len] + counts[bad_len]))
    lost |= set(range(first[bad_port], first[bad_port] + counts[bad_port]))
    applied = [b for i, b in enumerate(bodies) if i not in lost]

    c = await run_eth(dut, mii, frames, applied, 7, base, "corrupted frames")
    assert c["crc_errors"] == 2, f"crc_errors {c['crc_errors']}, expected 2"
    assert c["frames_ok"] == len(frames) - 2
    assert c["frames_dropped"] == 1, f"frames_dropped {c['frames_dropped']}, expected 1"
    assert c["seq_gaps"] == 1, f"seq_gaps {c['seq_gaps']}, expected 1"
    assert c["fifo_overflows"] == 0
    dut._log.info(f"corrupted frames: {len(lost)} messages lost in 2 bad frames "
                  f"({counts[bad_len] - lost_from} after a broken length, {counts[bad_port]} in a dropped frame), "
                  f"parser resynchronised at the next packet")
