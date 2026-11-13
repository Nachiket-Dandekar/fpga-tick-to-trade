import os
import random
import struct
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, ClockCycles

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from replay import mold_packets
from eth_frames import udp_frame, with_fcs
from itch_msgs import random_message, val

SESSION = b"T2TREPLAY "


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    dut.rst.value = 1
    dut.in_valid.value = 0
    dut.in_data.value = 0
    dut.in_start.value = 0
    dut.in_end.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)


async def send_frame(dut, frame, rng=None, gap=0.0):
    edge = RisingEdge(dut.clk)
    for i, b in enumerate(frame):
        while rng and rng.random() < gap:
            dut.in_valid.value = 0
            dut.in_start.value = 0
            await edge
        dut.in_valid.value = 1
        dut.in_data.value = b
        dut.in_start.value = 1 if i == 0 else 0
        await edge
    dut.in_valid.value = 0
    dut.in_start.value = 0
    await edge
    dut.in_end.value = 1
    await edge
    dut.in_end.value = 0
    await ClockCycles(dut.clk, 2)


async def monitor(dut, out):
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        if val(dut.out_valid):
            out["bytes"].append(val(dut.out_data))
            if val(dut.out_first):
                out["firsts"].append(len(out["bytes"]) - 1)
        if val(dut.seq_gap):
            out["gaps"] += 1


def start_monitor(dut):
    out = {"bytes": bytearray(), "firsts": [], "gaps": 0}
    cocotb.start_soon(monitor(dut, out))
    return out


def mold(seq, bodies):
    blocks = b"".join(struct.pack(">H", len(b)) + b for b in bodies)
    return SESSION + struct.pack(">QH", seq, len(bodies)) + blocks


def expect(payloads):
    data = bytearray()
    firsts = []
    for p in payloads:
        if len(p) > 20:
            firsts.append(len(data))
            data += p[20:]
    return data, firsts


def check_output(dut, out, payloads, name):
    data, firsts = expect(payloads)
    assert out["bytes"] == data, \
        f"{name}: forwarded {len(out['bytes'])} bytes, expected {len(data)}, contents differ"
    assert out["firsts"] == firsts, f"{name}: out_first positions differ"
    dut._log.info(f"{name}: {len(payloads)} packets, {len(data)} payload bytes matched, "
                  f"frames_dropped {val(dut.frames_dropped)}, seq_gaps {val(dut.seq_gaps)}")


def random_bodies(rng, n):
    bodies = []
    for _ in range(n):
        if rng.random() < 0.7:
            bodies.append(random_message(rng))
        else:
            bodies.append(bytes(rng.getrandbits(8) for _ in range(rng.randint(1, 80))))
    return bodies


@cocotb.test()
async def test_payload_exact(dut):
    await reset(dut)
    rng = random.Random(31)
    out = start_monitor(dut)
    payloads = []
    seq = 1
    while len(payloads) < 150:
        bodies = random_bodies(rng, rng.randint(1, 40))
        for p in mold_packets(bodies, SESSION, seq, rng.choice([30, 64, 200, 700, 1400])):
            payloads.append(p)
        seq += len(bodies)
    for p in payloads:
        await send_frame(dut, with_fcs(udp_frame(p)), rng, 0.3)
    check_output(dut, out, payloads, "payload")
    assert val(dut.frames_dropped) == 0 and val(dut.seq_gaps) == 0


@cocotb.test()
async def test_bad_frames_dropped(dut):
    await reset(dut)
    rng = random.Random(32)
    out = start_monitor(dut)
    bad_kinds = [
        dict(ethertype=0x86DD),
        dict(protocol=6),
        dict(version_ihl=0x46),
        dict(dst_port=26401),
        dict(udp_length=20),
        dict(udp_length=2000),
        "runt",
    ]
    good = []
    dropped = 0
    seq = 1
    for i in range(40):
        bodies = random_bodies(rng, rng.randint(1, 10))
        p = mold(seq, bodies)
        seq += len(bodies)
        good.append(p)
        await send_frame(dut, with_fcs(udp_frame(p)))

        kind = bad_kinds[i % len(bad_kinds)]
        junk = mold(rng.randrange(1 << 32), random_bodies(rng, 3))
        if kind == "runt":
            frame = udp_frame(junk)[:40]
        else:
            frame = udp_frame(junk, **kind)
        await send_frame(dut, with_fcs(frame))
        dropped += 1

    check_output(dut, out, good, "drops")
    assert val(dut.frames_dropped) == dropped, \
        f"frames_dropped {val(dut.frames_dropped)}, expected {dropped}"
    assert val(dut.seq_gaps) == 0


@cocotb.test()
async def test_padding_not_forwarded(dut):
    await reset(dut)
    rng = random.Random(33)
    out = start_monitor(dut)
    payloads = []
    seq = 1
    for i in range(60):
        if i % 5 == 0:
            p = mold(seq, [])
        else:
            bodies = [bytes(rng.getrandbits(8) for _ in range(rng.randint(1, 5)))]
            p = mold(seq, bodies)
            seq += 1
        payloads.append(p)
        await send_frame(dut, with_fcs(udp_frame(p, pad_to=rng.choice([60, 64, 128, 300]))))
    check_output(dut, out, payloads, "padding")
    assert val(dut.frames_dropped) == 0 and val(dut.seq_gaps) == 0


@cocotb.test()
async def test_sequence_gaps(dut):
    await reset(dut)
    rng = random.Random(34)
    out = start_monitor(dut)
    plan = [
        (1000, 3, True),
        (1003, 2, True),
        (1005, 0, True),
        (1005, 1, True),
        (99, 4, False),
        (1006, 2, True),
        (1010, 2, True),
        (1012, 1, True),
        (1012, 1, True),
        (1013, 5, True),
        (1018, 1, True),
    ]
    expected_gaps = 2
    payloads = []
    for seq, count, deliver in plan:
        p = mold(seq, random_bodies(rng, count))
        if deliver:
            payloads.append(p)
            await send_frame(dut, with_fcs(udp_frame(p)))
        else:
            await send_frame(dut, with_fcs(udp_frame(p, dst_port=26401)))
    check_output(dut, out, payloads, "sequence")
    assert out["gaps"] == expected_gaps, f"seq_gap pulsed {out['gaps']} times, expected {expected_gaps}"
    assert val(dut.seq_gaps) == expected_gaps
    assert val(dut.frames_dropped) == 1
