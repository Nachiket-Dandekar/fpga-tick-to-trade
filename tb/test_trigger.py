import os
import random
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, ClockCycles

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from strategy import Strategy
from itch_msgs import val


async def reset_dut(dut, limit_price=0xFFFFFFFF, max_qty=500):
    await RisingEdge(dut.clk)
    dut.rst.value = 1
    dut.limit_price.value = limit_price
    dut.max_qty.value = max_qty
    dut.book_update.value = 0
    dut.ask_valid.value = 0
    dut.ask_price.value = 0
    dut.ask_qty.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def step_update(dut, strat, ask_valid, ask_price, ask_qty, gap_cycles=0):
    for _ in range(gap_cycles):
        await RisingEdge(dut.clk)
        dut.book_update.value = 0
        await ReadOnly()
        assert val(dut.order_valid) == 0, "order_valid asserted without book_update"
    await RisingEdge(dut.clk)
    dut.book_update.value = 1
    dut.ask_valid.value = 1 if ask_valid else 0
    dut.ask_price.value = ask_price
    dut.ask_qty.value = ask_qty
    await RisingEdge(dut.clk)
    dut.book_update.value = 0
    await ReadOnly()

    exp = strat.step(ask_valid, ask_price, ask_qty)
    got_valid = val(dut.order_valid)
    if exp is None:
        assert got_valid == 0, (
            f"unexpected order fired for valid={ask_valid} price={ask_price} qty={ask_qty}"
        )
    else:
        assert got_valid == 1, (
            f"missed order for valid={ask_valid} price={ask_price} qty={ask_qty}"
        )
        assert val(dut.order_price) == exp["price"], (
            f"order_price {val(dut.order_price)} != {exp['price']}"
        )
        assert val(dut.order_shares) == exp["shares"], (
            f"order_shares {val(dut.order_shares)} != {exp['shares']}"
        )


@cocotb.test()
async def test_directed_edges(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    limit_px = 250_000
    max_q = 500
    strat = Strategy(limit_price=limit_px, max_qty=max_q)
    await reset_dut(dut, limit_price=limit_px, max_qty=max_q)

    seq = [
        (0, 200_000, 100, 1),
        (1, 200_000, 100, 0),
        (1, 200_000, 300, 2),
        (1, 200_000, 900, 0),
        (0, 0, 0, 1),
        (1, 200_000, 100, 0),
        (1, limit_px - 1, 499, 0),
        (1, limit_px, 500, 1),
        (1, limit_px + 1, 100, 0),
        (1, limit_px, 501, 2),
        (1, limit_px + 100, 200, 0),
        (1, limit_px + 100, 300, 0),
        (1, limit_px - 100, 1200, 1),
    ]
    for av, ap, aq, gap in seq:
        await step_update(dut, strat, av, ap, aq, gap)

    strat.reset()
    await reset_dut(dut, limit_price=limit_px, max_qty=max_q)
    await step_update(dut, strat, 1, limit_px - 100, 250, 0)
    assert len(strat.orders) == 1


@cocotb.test()
async def test_random_sequences(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    rng = random.Random(42)

    for trial in range(5):
        limit_px = rng.choice([0xFFFFFFFF, 100_000, 374_300, 500_000])
        max_q = rng.choice([100, 500, 1000])
        strat = Strategy(limit_price=limit_px, max_qty=max_q)
        await reset_dut(dut, limit_price=limit_px, max_qty=max_q)

        cur_px = 374_300
        for _ in range(400):
            r = rng.random()
            if r < 0.15:
                av = 0
                ap = rng.randint(0, 600_000)
            elif r < 0.45:
                av = 1
                ap = cur_px
            elif r < 0.65 and limit_px != 0xFFFFFFFF:
                av = 1
                ap = limit_px + rng.choice([-1, 0, 1])
                cur_px = ap
            else:
                av = 1
                ap = rng.randint(50_000, 600_000)
                cur_px = ap
            aq = rng.choice([1, max_q - 1, max_q, max_q + 1, rng.randint(1, 2500)])
            gap = rng.choice([0, 0, 1, 3])
            await step_update(dut, strat, av, ap, aq, gap)
