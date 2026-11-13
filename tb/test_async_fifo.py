import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ClockCycles, Timer

from itch_msgs import val

DEPTH = 16


async def start(dut, wr_period, rd_period, rd_phase):
    cocotb.start_soon(Clock(dut.wr_clk, wr_period, unit="ns").start())
    await Timer(rd_phase, unit="ns")
    cocotb.start_soon(Clock(dut.rd_clk, rd_period, unit="ns").start())
    dut.wr_en.value = 0
    dut.wr_data.value = 0
    dut.rd_en.value = 0
    dut.wr_rst.value = 1
    dut.rd_rst.value = 1
    await ClockCycles(dut.wr_clk, 4)
    await ClockCycles(dut.rd_clk, 4)
    dut.wr_rst.value = 0
    dut.rd_rst.value = 0
    await ClockCycles(dut.wr_clk, 4)
    await ClockCycles(dut.rd_clk, 4)


async def writer(dut, rng, count, p_write, sent, stats):
    width = len(dut.wr_data)
    while len(sent) < count:
        await FallingEdge(dut.wr_clk)
        full = val(dut.full)
        stats["full"] += full
        want = rng.random() < p_write
        data = rng.getrandbits(width)
        if full and want and rng.random() < 0.3:
            dut.wr_en.value = 1
            dut.wr_data.value = data
            stats["pushed_when_full"] += 1
        elif want and not full:
            dut.wr_en.value = 1
            dut.wr_data.value = data
            sent.append(data)
        else:
            dut.wr_en.value = 0
    await FallingEdge(dut.wr_clk)
    dut.wr_en.value = 0


async def reader(dut, rng, p_read, got, stats):
    while True:
        await FallingEdge(dut.rd_clk)
        empty = val(dut.empty)
        stats["empty"] += empty
        if not empty and rng.random() < p_read:
            got.append(val(dut.rd_data))
            dut.rd_en.value = 1
        else:
            dut.rd_en.value = 0


async def run(dut, name, wr_period, rd_period, rd_phase, p_write, p_read, seed, count=3000):
    await start(dut, wr_period, rd_period, rd_phase)
    rng = random.Random(seed)
    sent, got = [], []
    stats = {"full": 0, "empty": 0, "pushed_when_full": 0}
    rd = cocotb.start_soon(reader(dut, rng, p_read, got, stats))
    await writer(dut, rng, count, p_write, sent, stats)
    for _ in range(4000):
        await ClockCycles(dut.rd_clk, 1)
        if len(got) == len(sent):
            break
    await ClockCycles(dut.rd_clk, 10)
    rd.cancel()

    assert len(got) == len(sent), f"{name}: sent {len(sent)}, read {len(got)}"
    for i, (g, s) in enumerate(zip(got, sent)):
        assert g == s, f"{name}: word {i} read {g:#x}, expected {s:#x}"
    assert val(dut.empty) == 1, f"{name}: fifo not empty after draining"
    dut._log.info(f"{name}: {len(sent)} words in order, full seen {stats['full']} write cycles, "
                  f"empty seen {stats['empty']} read cycles, "
                  f"{stats['pushed_when_full']} writes refused while full")
    return stats


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def test_write_faster_than_read(dut):
    stats = await run(dut, "write faster", 7, 23, 3.1, 0.9, 0.8, 1)
    assert stats["full"] > 0, "fifo never filled"
    assert stats["pushed_when_full"] > 0


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def test_read_faster_than_write(dut):
    stats = await run(dut, "read faster", 40, 10, 4.3, 0.7, 0.9, 2)
    assert stats["empty"] > 0


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def test_close_clocks_drift(dut):
    await run(dut, "close clocks", 10, 10.3, 6.9, 0.8, 0.7, 3)


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def test_bursts_both_ways(dut):
    await start(dut, 13, 9, 2.2)
    rng = random.Random(4)
    sent, got = [], []
    stats = {"full": 0, "empty": 0, "pushed_when_full": 0}
    rd = cocotb.start_soon(reader(dut, rng, 0.05, got, stats))
    for burst in range(20):
        p_read = 0.05 if burst % 2 == 0 else 1.0
        rd.cancel()
        rd = cocotb.start_soon(reader(dut, rng, p_read, got, stats))
        await writer(dut, rng, len(sent) + rng.randint(5, 60), 1.0, sent, stats)
    rd.cancel()
    rd = cocotb.start_soon(reader(dut, rng, 1.0, got, stats))
    for _ in range(2000):
        await ClockCycles(dut.rd_clk, 1)
        if len(got) == len(sent):
            break
    rd.cancel()
    assert got == sent, f"bursts: sent {len(sent)}, read {len(got)}, first mismatch at " \
        f"{next((i for i, (g, s) in enumerate(zip(got, sent)) if g != s), min(len(got), len(sent)))}"
    assert stats["full"] > 0 and stats["empty"] > 0
    dut._log.info(f"bursts: {len(sent)} words in order, full {stats['full']}, empty {stats['empty']}")
