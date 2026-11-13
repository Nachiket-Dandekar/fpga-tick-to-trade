import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ClockCycles

from itch_msgs import val


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    dut.rst.value = 1
    dut.in_valid.value = 0
    dut.in_data.value = 0
    dut.out_ready.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0


async def run_phase(dut, rng, model, stats, cycles, p_in, p_out):
    width = len(dut.in_data)
    depth = 1 << int(dut.ADDR.value)
    waiting = 0
    for _ in range(cycles):
        await FallingEdge(dut.clk)
        full = val(dut.full)
        out_valid = val(dut.out_valid)
        level = val(dut.level)

        assert val(dut.overflow) == stats["expect_overflow"], \
            f"overflow is {val(dut.overflow)}, expected {int(stats['expect_overflow'])}"
        assert len(model) == level + out_valid, \
            f"model holds {len(model)}, fifo level {level} + out_valid {out_valid}"
        assert full == (level == depth), f"full {full} with level {level}"
        if out_valid:
            assert val(dut.out_data) == model[0], \
                f"out_data {val(dut.out_data):#x}, expected {model[0]:#x}"
            waiting = 0
        elif model:
            waiting += 1
            assert waiting <= 2, "data waiting in the fifo but out_valid stays low"

        stats["full"] += full
        stats["empty"] += not model
        stats["max"] = max(stats["max"], len(model))

        in_valid = rng.random() < p_in
        out_ready = rng.random() < p_out
        data = rng.getrandbits(width)
        dut.in_valid.value = in_valid
        dut.in_data.value = data
        dut.out_ready.value = out_ready

        if out_valid and out_ready:
            model.popleft()
            stats["popped"] += 1
        stats["expect_overflow"] = in_valid and full
        if in_valid and not full:
            model.append(data)
            stats["pushed"] += 1
        if in_valid and full:
            stats["overflows"] += 1


@cocotb.test()
async def test_random_against_deque(dut):
    await reset(dut)
    rng = random.Random(41)
    model = deque()
    depth = 1 << int(dut.ADDR.value)
    stats = dict(expect_overflow=False, full=0, empty=0, max=0, pushed=0, popped=0, overflows=0)
    phases = [
        (2000, 0.9, 0.2),
        (2000, 0.2, 0.9),
        (2000, 0.5, 0.5),
        (2000, 1.0, 1.0),
        (depth + 100, 1.0, 0.0),
        (depth + 100, 0.0, 1.0),
        (3000, 0.7, 0.6),
        (depth + 100, 0.0, 1.0),
    ]
    for cycles, p_in, p_out in phases:
        await run_phase(dut, rng, model, stats, cycles, p_in, p_out)
    assert stats["full"] > 0 and stats["empty"] > 0 and stats["overflows"] > 0
    dut._log.info(f"depth {depth}: {stats['pushed']} pushed, {stats['popped']} popped, "
                  f"{stats['overflows']} overflows, {stats['full']} cycles full, "
                  f"{stats['empty']} cycles empty, max held {stats['max']}, all matched")
