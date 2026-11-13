import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly

from itch_msgs import LENGTHS, add_order, random_message, frame, read_itch_file, val

FIELDS = ["msg_type", "stock_locate", "order_ref", "new_order_ref",
          "side", "shares", "stock", "price"]


def be(body, start, n):
    return int.from_bytes(body[start:start + n], "big")


def decode(body):
    out = dict.fromkeys(FIELDS, 0)
    t = chr(body[0])
    out["msg_type"] = body[0]
    out["stock_locate"] = be(body, 1, 2)
    if t in "AF":
        out["order_ref"] = be(body, 11, 8)
        out["side"] = 1 if body[19] == ord("B") else 0
        out["shares"] = be(body, 20, 4)
        out["stock"] = be(body, 24, 8)
        out["price"] = be(body, 32, 4)
    elif t in "ECX":
        out["order_ref"] = be(body, 11, 8)
        out["shares"] = be(body, 19, 4)
    elif t == "D":
        out["order_ref"] = be(body, 11, 8)
    elif t == "U":
        out["order_ref"] = be(body, 11, 8)
        out["new_order_ref"] = be(body, 19, 8)
        out["shares"] = be(body, 27, 4)
        out["price"] = be(body, 31, 4)
    return out


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.byte_valid.value = 0
    dut.byte_first.value = 0
    dut.byte_data.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0


async def drive(dut, data, gap_chance=0.0, rng=None):
    for b in data:
        while rng and rng.random() < gap_chance:
            dut.byte_valid.value = 0
            await RisingEdge(dut.clk)
        dut.byte_valid.value = 1
        dut.byte_data.value = b
        await RisingEdge(dut.clk)
    dut.byte_valid.value = 0


async def monitor(dut, results):
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        if val(dut.msg_valid):
            results.append({f: val(getattr(dut, f)) for f in FIELDS})


async def run_and_check(dut, bodies, gap_chance=0.0, seed=1):
    await reset(dut)
    results = []
    cocotb.start_soon(monitor(dut, results))
    await drive(dut, frame(bodies), gap_chance, random.Random(seed))
    for _ in range(5):
        await RisingEdge(dut.clk)

    assert len(results) == len(bodies), \
        f"expected {len(bodies)} messages, got {len(results)}"
    for i, (body, got) in enumerate(zip(bodies, results)):
        exp = decode(body)
        bad = [f for f in FIELDS if got[f] != exp[f]]
        assert not bad, (f"message {i} type {chr(body[0])}: " +
                         ", ".join(f"{f} got {got[f]:#x} expected {exp[f]:#x}" for f in bad))
    dut._log.info(f"{len(bodies)} messages matched")


@cocotb.test()
async def test_one_add_order(dut):
    await run_and_check(dut, [add_order(ref=42, side="B", shares=100,
                                        stock="AAPL", price=1_500_000)])


@cocotb.test()
async def test_each_type(dut):
    rng = random.Random(7)
    bodies = []
    for t in LENGTHS:
        body = bytearray(rng.getrandbits(8) for _ in range(LENGTHS[t]))
        body[0] = ord(t)
        if t in "AF":
            body[19] = ord("S")
        bodies.append(bytes(body))
    await run_and_check(dut, bodies)


@cocotb.test()
async def test_random_no_gaps(dut):
    rng = random.Random(1)
    await run_and_check(dut, [random_message(rng) for _ in range(10_000)])


@cocotb.test()
async def test_random_with_gaps(dut):
    rng = random.Random(2)
    await run_and_check(dut, [random_message(rng) for _ in range(10_000)],
                        gap_chance=0.3, seed=3)


@cocotb.test(skip=not os.environ.get("ITCH_FILE"))
async def test_real_nasdaq(dut):
    bodies = read_itch_file(os.environ["ITCH_FILE"],
                            int(os.environ.get("ITCH_LIMIT", "100000")))
    await run_and_check(dut, bodies)
    await run_and_check(dut, bodies, gap_chance=0.3, seed=4)


async def drive_first(dut, data):
    dut.byte_first.value = 1
    dut.byte_valid.value = 1
    dut.byte_data.value = data[0]
    await RisingEdge(dut.clk)
    dut.byte_first.value = 0
    await drive(dut, data[1:])


async def pulse_reset(dut):
    dut.rst.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0


async def run_resync(dut, before, cut, after):
    await pulse_reset(dut)
    results = []
    cocotb.start_soon(monitor(dut, results))
    broken = frame([before[-1]])[:cut]
    await drive(dut, frame(before[:-1]) + broken)
    await drive_first(dut, frame(after))
    for _ in range(5):
        await RisingEdge(dut.clk)

    expected = before[:-1] + after
    assert len(results) == len(expected), \
        f"cut at {cut}: expected {len(expected)} messages, got {len(results)}"
    for i, (body, got) in enumerate(zip(expected, results)):
        exp = decode(body)
        bad = [f for f in FIELDS if got[f] != exp[f]]
        assert not bad, f"cut at {cut}, message {i}: " + ", ".join(bad)


@cocotb.test()
async def test_resync_on_byte_first(dut):
    rng = random.Random(9)
    await reset(dut)
    for cut in [0, 1, 2, 3, 10, 30, 37]:
        before = [random_message(rng) for _ in range(5)]
        before[-1] = add_order(ref=7, side="S", shares=5, stock="CUT", price=1)
        after = [random_message(rng) for _ in range(50)]
        await run_resync(dut, before, cut, after)
    huge = bytes([0xFF, 0xFF]) + b"x" * 20
    await pulse_reset(dut)
    results = []
    cocotb.start_soon(monitor(dut, results))
    after = [random_message(rng) for _ in range(50)]
    await drive(dut, huge)
    await drive_first(dut, frame(after))
    for _ in range(5):
        await RisingEdge(dut.clk)
    assert [r["msg_type"] for r in results] == [b[0] for b in after]
    dut._log.info("resync: messages after byte_first matched for every cut point")
