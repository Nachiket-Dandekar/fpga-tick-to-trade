import os
import random
import statistics
import struct
import sys
import time

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, ClockCycles, Timer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import book as model
from replay import mold_packets
from strategy import run_strategy, pack_order_payload
from eth_frames import PREAMBLE, MIN_IFG, MiiDriver, MiiMonitor, nibbles, parse_order_frame, udp_frame, with_fcs
from itch_msgs import add_order, delete, read_itch_file, val
from test_order_book import random_flow, snapshot, fmt, P

COUNTERS = ["frames_ok", "crc_errors", "frames_dropped", "seq_gaps",
            "fifo_overflows", "msg_count", "fifo_max", "orders_sent",
            "orders_dropped", "last_latency", "min_latency", "max_latency"]
CLEAR_CYCLES = 8200
UDP_HEADERS = 42
OFFSET_MIN_NS = 190.0
OFFSET_MAX_NS = 240.0


async def start(dut, locate, base):
    cocotb.start_soon(Clock(dut.rx_clk, 40, unit="ns").start())
    await Timer(13.7, unit="ns")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await Timer(7.4, unit="ns")
    cocotb.start_soon(Clock(dut.tx_clk, 40, unit="ns").start())
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
                and not val(dut.book.busy) and val(dut.tx_path.q_count) == 0
                and val(dut.tx_path.state) == 0 and val(dut.tx_path.tx_empty)):
            break
    await ClockCycles(dut.clk, 20)


def counters(dut):
    return {c: val(getattr(dut, c)) for c in COUNTERS}


def frames_for(bodies):
    return [bytearray(with_fcs(udp_frame(p))) for p in mold_packets(bodies)]


def map_target_messages_in_frames(frames, target_indices):
    by_frame = {}
    msg_idx = 0
    for f_idx, frame in enumerate(frames):
        count = struct.unpack(">H", frame[60:62])[0]
        pos = 62
        targets = {}
        for _ in range(count):
            msg_idx += 1
            length = struct.unpack(">H", frame[pos:pos + 2])[0]
            last_byte_offset = pos + 2 + length - 1
            if msg_idx in target_indices:
                nibble_idx = 2 * (8 + last_byte_offset) + 1
                targets[nibble_idx] = (msg_idx, frame[last_byte_offset])
            pos += 2 + length
        if targets:
            by_frame[f_idx] = targets
    return by_frame


async def capture_t_in(dut, msg_idx, expected_byte, t_in_by_msg):
    await ClockCycles(dut.clk, 6)
    for _ in range(10):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if val(dut.rx_valid):
            got_byte = val(dut.rx_data)
            assert got_byte == expected_byte, (
                f"msg {msg_idx}: expected last byte 0x{expected_byte:02x}, got 0x{got_byte:02x}"
            )
            t_in_by_msg[msg_idx] = val(dut.cycle_cnt)
            return
    raise AssertionError(f"msg {msg_idx}: did not see rx_valid within expected crossing window")


async def watch_t_out(dut, t_outs):
    while True:
        await dut.tx_path.state.value_change
        await ReadOnly()
        if val(dut.tx_path.state) == 1:
            while not (val(dut.tx_path.tx_wr_en) and val(dut.tx_path.byte_idx) == 0):
                await RisingEdge(dut.clk)
                await ReadOnly()
            t_outs.append(val(dut.cycle_cnt))


async def send_frame_tracked(dut, mii, frame_bytes, targets, rx_pin_ps, t_in_by_msg):
    from cocotb.utils import get_sim_time
    nibble_list = nibbles(PREAMBLE + frame_bytes)
    edge = RisingEdge(mii.clk)
    mii.dv.value = 1
    for i, n in enumerate(nibble_list):
        mii.rxd.value = n
        await edge
        if i in targets:
            msg_idx, last_byte = targets[i]
            rx_pin_ps[msg_idx] = get_sim_time("ps")
            cocotb.start_soon(capture_t_in(dut, msg_idx, last_byte, t_in_by_msg))
    mii.dv.value = 0
    mii.rxd.value = 0
    await ClockCycles(mii.clk, MIN_IFG)


async def run_eth(dut, mii, frames, applied, locate, base, name, check_orders=False):
    ref = model.Book(locate, base)
    expected = [s for s in (ref.process(b) for b in applied) if s is not None]

    exp_orders = []
    frame_targets = {}
    rx_pin_ps = {}
    t_in_by_msg = {}
    t_outs = []
    tx_mon = None
    out_watcher = None

    if check_orders:
        _, exp_orders = run_strategy(applied, locate, base)
        target_indices = {o["msg_index"] for o in exp_orders}
        frame_targets = map_target_messages_in_frames(frames, target_indices)
        tx_mon = MiiMonitor(dut, clk=dut.tx_clk, tx_en=dut.mii_tx_en, txd=dut.mii_txd)
        out_watcher = cocotb.start_soon(watch_t_out(dut, t_outs))

    results = []
    mon = cocotb.start_soon(book_monitor(dut, results))
    t0 = time.time()
    for f_idx, frame in enumerate(frames):
        if f_idx in frame_targets:
            await send_frame_tracked(dut, mii, bytes(frame), frame_targets[f_idx], rx_pin_ps, t_in_by_msg)
        else:
            await mii.send(bytes(frame))
    await drain(dut)
    mon.cancel()
    if out_watcher is not None:
        out_watcher.cancel()
    if tx_mon is not None:
        tx_mon.stop()

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

    if check_orders:
        assert val(dut.tx_underrun) == 0, f"{name}: tx_underrun asserted"
        assert c["orders_dropped"] == 0, f"{name}: orders_dropped {c['orders_dropped']}"
        assert c["orders_sent"] == len(exp_orders), (
            f"{name}: orders_sent {c['orders_sent']}, expected {len(exp_orders)}"
        )
        assert len(tx_mon.frames) == len(exp_orders), (
            f"{name}: captured {len(tx_mon.frames)} order frames, expected {len(exp_orders)}"
        )
        assert len(t_outs) == len(exp_orders), (
            f"{name}: captured {len(t_outs)} t_out timestamps, expected {len(exp_orders)}"
        )

        cyc_lats = []
        p2p_ns_list = []
        offsets_ns = []

        for idx, (frame_info, exp_o) in enumerate(zip(tx_mon.frames, exp_orders), 1):
            p = parse_order_frame(frame_info)
            m_idx = exp_o["msg_index"]
            assert p["order_num"] == idx, f"{name}: order {idx} order_num {p['order_num']}"
            assert p["token"] == exp_o["token"], f"{name}: order {idx} token {p['token']} != {exp_o['token']}"
            assert p["shares"] == exp_o["shares"], f"{name}: order {idx} shares {p['shares']} != {exp_o['shares']}"
            assert p["price"] == exp_o["price"], f"{name}: order {idx} price {p['price']} != {exp_o['price']}"
            assert p["msg_index"] == m_idx, f"{name}: order {idx} msg_index {p['msg_index']} != {m_idx}"
            exp_payload = pack_order_payload(idx, exp_o["shares"], exp_o["price"], p["latency"], m_idx)
            assert frame_info["body"][42:99] == exp_payload
            if idx > 1 and p["ifg_nibbles"] is not None:
                assert p["ifg_nibbles"] >= 24, f"{name}: order {idx} ifg {p['ifg_nibbles']} nibbles (< 24)"

            exp_lat = (t_outs[idx - 1] - t_in_by_msg[m_idx]) & 0xFFFFFF
            assert p["latency"] == exp_lat, (
                f"{name}: order {idx} (msg {m_idx}) latency field {p['latency']} != t_out - t_in ({exp_lat})"
            )

            p2p_ns = (frame_info["start_ps"] - rx_pin_ps[m_idx]) / 1000.0
            offset_ns = p2p_ns - (p["latency"] * 10.0)
            assert OFFSET_MIN_NS <= offset_ns <= OFFSET_MAX_NS, (
                f"{name}: order {idx} offset {offset_ns:.1f} ns outside [{OFFSET_MIN_NS}, {OFFSET_MAX_NS}] ns"
            )
            cyc_lats.append(p["latency"])
            p2p_ns_list.append(p2p_ns)
            offsets_ns.append(offset_ns)

        if cyc_lats:
            assert c["last_latency"] == cyc_lats[-1]
            assert c["min_latency"] == min(cyc_lats)
            assert c["max_latency"] == max(cyc_lats)
            dut._log.info(
                f"{name} latency cycles: min={min(cyc_lats)} "
                f"median={statistics.median(cyc_lats):.1f} max={max(cyc_lats)}"
            )
            dut._log.info(
                f"{name} pin-to-pin ns: min={min(p2p_ns_list):.1f} "
                f"median={statistics.median(p2p_ns_list):.1f} max={max(p2p_ns_list):.1f} "
                f"(offset min={min(offsets_ns):.1f} max={max(offsets_ns):.1f} ns)"
            )

    dut._log.info(f"{name}: {len(applied)} messages in {len(frames)} frames, "
                  f"{len(expected)} book updates matched, {len(exp_orders)} orders matched, "
                  f"collisions {ref.collisions}, out of range {ref.out_of_range}, {time.time() - t0:.0f} s")
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
    c = await run_eth(dut, mii, frames, bodies, 7, base, "random flow", check_orders=True)
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


@cocotb.test()
async def test_order_behind_scan(dut):
    locate, other = 7, 8
    base = P(100.00)
    mii = await start(dut, locate, base)

    bodies = [
        add_order(1, "S", 100, "FAR", base + (model.LEVELS - 1) * model.TICK, locate),
        add_order(2, "S", 100, "NEAR", base + 100 * model.TICK, locate),
        delete(2, locate),
        add_order(3, "S", 100, "BEST", base + 50 * model.TICK, locate),
    ]
    bodies += [add_order(100 + i, "B", 10, "OTHER", P(20.00), other) for i in range(12)]

    frames = frames_for(bodies)
    c = await run_eth(dut, mii, frames, bodies, locate, base, "order behind scan", check_orders=True)
    check_clean(c, frames)
    assert c["orders_sent"] == 4, f"orders_sent {c['orders_sent']}, expected 4"
    assert c["last_latency"] > 1000, f"last order did not wait behind the scan: {c['last_latency']} cycles"


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
    c = await run_eth(dut, mii, frames, bodies, locate, base, f"{ticker} over ethernet", check_orders=True)
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
