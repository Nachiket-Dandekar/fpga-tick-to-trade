import os
import random
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import book as model
from itch_msgs import (add_order, executed, executed_price, cancel, delete, replace,
                       frame, read_itch_file, val)

SNAP = ["bid_valid", "bid_price", "bid_qty", "ask_valid", "ask_price", "ask_qty"]


def P(dollars):
    return round(dollars * 10000)


def fmt(s):
    bv, bp, bq, av, ap, aq = s
    bid = f"{bq} @ {bp / 10000:.2f}" if bv else "none"
    ask = f"{aq} @ {ap / 10000:.2f}" if av else "none"
    return f"bid {bid}, ask {ask}"


def snapshot(dut):
    bv, bp, bq, av, ap, aq = (val(getattr(dut, s)) for s in SNAP)
    return (bv, bp if bv else 0, bq if bv else 0, av, ap if av else 0, aq if av else 0)


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.byte_valid.value = 0
    dut.byte_first.value = 0
    dut.byte_data.value = 0
    await RisingEdge(dut.clk)


async def reset(dut, locate, base):
    dut.target_locate.value = locate
    dut.base_price.value = base
    dut.rst.value = 1
    dut.byte_valid.value = 0
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
        while True:
            await FallingEdge(dut.clk)
            if val(dut.byte_ready):
                break
        await RisingEdge(dut.clk)
    dut.byte_valid.value = 0


async def monitor(dut, locate, results, latency):
    cycle = 0
    started = []
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        cycle += 1
        if (val(dut.parser.msg_valid) and val(dut.parser.stock_locate) == locate
                and chr(val(dut.parser.msg_type)) in "AFECXDU"):
            started.append(cycle)
        if val(dut.book_update):
            results.append(snapshot(dut))
            latency.append(cycle - started.pop(0))


async def run_book(dut, bodies, locate, base, gap_chance=0.0, seed=1, name=""):
    ref = model.Book(locate, base)
    expected = [s for s in (ref.process(b) for b in bodies) if s is not None]

    await reset(dut, locate, base)
    results, latency = [], []
    mon = cocotb.start_soon(monitor(dut, locate, results, latency))
    await drive(dut, frame(bodies), gap_chance, random.Random(seed))
    for _ in range(20_000):
        if len(results) >= len(expected):
            break
        await RisingEdge(dut.clk)
    for _ in range(5):
        await RisingEdge(dut.clk)
    mon.cancel()

    assert len(results) == len(expected), \
        f"{name}: expected {len(expected)} book updates, got {len(results)}"
    for i, (got, exp) in enumerate(zip(results, expected)):
        assert got == exp, f"{name}: update {i}: got {fmt(got)}, expected {fmt(exp)}"
    assert val(dut.collisions) == ref.collisions, \
        f"{name}: collisions {val(dut.collisions)}, expected {ref.collisions}"
    assert val(dut.out_of_range) == ref.out_of_range, \
        f"{name}: out_of_range {val(dut.out_of_range)}, expected {ref.out_of_range}"

    if latency:
        dut._log.info(
            f"{name}: {len(expected)} book updates matched, "
            f"collisions {ref.collisions}, out of range {ref.out_of_range}, "
            f"latency min {min(latency)} avg {sum(latency) / len(latency):.1f} max {max(latency)} cycles")
    return expected, latency


@cocotb.test()
async def test_scenario(dut):
    L, O = 7, 8
    same_set = [(k << model.SET_BITS) | (100 ^ k) for k in range(5)]
    assert len({model.set_index(r) for r in same_set}) == 1

    steps = [
        (add_order(1, "B", 100, "T", P(10.00), L), (1, P(10.00), 100, 0, 0, 0)),
        (add_order(2, "B", 200, "T", P(10.01), L), (1, P(10.01), 200, 0, 0, 0)),
        (add_order(3, "S", 300, "T", P(10.05), L), (1, P(10.01), 200, 1, P(10.05), 300)),
        (add_order(4, "S", 50, "T", P(10.03), L),  (1, P(10.01), 200, 1, P(10.03), 50)),
        (add_order(5, "B", 100, "T", P(10.01), L), (1, P(10.01), 300, 1, P(10.03), 50)),
        (add_order(60, "B", 999, "X", P(10.50), O), None),
        (executed(2, 50, L),                       (1, P(10.01), 250, 1, P(10.03), 50)),
        (cancel(5, 100, L),                        (1, P(10.01), 150, 1, P(10.03), 50)),
        (executed_price(2, 25, P(10.01), L),       (1, P(10.01), 125, 1, P(10.03), 50)),
        (delete(2, L),                             (1, P(10.00), 100, 1, P(10.03), 50)),
        (replace(4, 6, 75, P(10.02), L),           (1, P(10.00), 100, 1, P(10.02), 75)),
        (delete(6, L),                             (1, P(10.00), 100, 1, P(10.05), 300)),
        (delete(3, L),                             (1, P(10.00), 100, 0, 0, 0)),
        (delete(1, L),                             (0, 0, 0, 0, 0, 0)),
        (delete(999_999, L),                       (0, 0, 0, 0, 0, 0)),
        (add_order(same_set[0], "B", 10, "T", P(5.00), L), (1, P(5.00), 10, 0, 0, 0)),
        (add_order(same_set[1], "B", 10, "T", P(5.01), L), (1, P(5.01), 10, 0, 0, 0)),
        (add_order(same_set[2], "B", 10, "T", P(5.02), L), (1, P(5.02), 10, 0, 0, 0)),
        (add_order(same_set[3], "B", 10, "T", P(5.03), L), (1, P(5.03), 10, 0, 0, 0)),
        (add_order(same_set[4], "B", 10, "T", P(5.04), L), (1, P(5.03), 10, 0, 0, 0)),
        (add_order(70, "S", 10, "T", P(50.00), L),         (1, P(5.03), 10, 0, 0, 0)),
        (replace(888_888, 71, 10, P(5.00), L),             (1, P(5.03), 10, 0, 0, 0)),
        (executed(same_set[3], 4, L),                      (1, P(5.03), 6, 0, 0, 0)),
        (add_order(72, "S", 20, "T", P(6.00), L),          (1, P(5.03), 6, 1, P(6.00), 20)),
        (cancel(same_set[3], 500, L),                      (1, P(5.02), 10, 1, P(6.00), 20)),
        (add_order(73, "B", 0, "T", P(5.50), L),           (1, P(5.02), 10, 1, P(6.00), 20)),
        (delete(73, L),                                    (1, P(5.02), 10, 1, P(6.00), 20)),
        (executed(72, 0, L),                               (1, P(5.02), 10, 1, P(6.00), 20)),
        (replace(same_set[2], 74, 0, P(5.60), L),          (1, P(5.01), 10, 1, P(6.00), 20)),
    ]

    ref = model.Book(L, 0)
    for i, (body, exp) in enumerate(steps):
        got = ref.process(body)
        assert got == exp, f"model step {i}: got {got}, expected {exp}"
    assert ref.collisions == 1 and ref.out_of_range == 1

    await start_clock(dut)
    await run_book(dut, [b for b, _ in steps], L, 0, name="scenario")


@cocotb.test()
async def test_edges(dut):
    L = 7
    top_price = (model.LEVELS - 1) * model.TICK
    same_set = [(k << model.SET_BITS) | (200 ^ k) for k in range(5)]
    assert len({model.set_index(r) for r in same_set}) == 1

    bodies = [add_order(900, "B", 10, "T", 0, L), delete(900, L),
              add_order(904, "S", 10, "T", top_price, L), delete(904, L)]
    edge_updates = len(bodies)
    bodies += [add_order(same_set[0], "B", 0, "T", P(1.00), L)]
    bodies += [add_order(r, "B", 10, "T", P(1.00), L) for r in same_set[1:]]

    await start_clock(dut)
    expected, latency = await run_book(dut, bodies, L, 0, name="edges")
    assert expected[-1] == (1, P(1.00), 40, 0, 0, 0), f"edges: model ended at {fmt(expected[-1])}"
    assert max(latency[:edge_updates]) < 20, f"edges: latency {latency[:edge_updates]}"


def random_flow(rng, n, locate=7, other=8, mid=P(20.00)):
    bodies = []
    live = {}
    next_ref = 4
    for i in range(n):
        r = rng.random()
        grow = i < n // 3
        if r < 0.15:
            bodies.append(add_order(next_ref, rng.choice("BS"), rng.randint(1, 500), "OTHER",
                                    mid + 100 * rng.randint(-30, 30), other))
            next_ref += 4
        elif not live or r < (0.9 if grow else 0.5):
            side = rng.choice("BS")
            if rng.random() < 0.02:
                ticks = rng.randint(-2200, 2200)
            else:
                ticks = rng.randint(1, 40) * (-1 if side == "B" else 1)
            price = max(100, mid + 100 * ticks)
            shares = rng.randint(1, 1000)
            bodies.append(add_order(next_ref, side, shares, "TEST", price, locate))
            live[next_ref] = shares
            next_ref += 4
        else:
            ref = rng.choice(list(live))
            r = rng.random()
            if r < 0.3:
                s = rng.randint(1, live[ref])
                bodies.append(executed(ref, s, locate) if rng.random() < 0.7
                              else executed_price(ref, s, mid, locate))
                live[ref] -= s
            elif r < 0.5:
                s = rng.randint(1, live[ref])
                if rng.random() < 0.1:
                    s = live[ref] + rng.randint(1, 500)
                bodies.append(cancel(ref, s, locate))
                live[ref] = max(0, live[ref] - s)
            elif r < 0.8:
                bodies.append(delete(ref, locate))
                live[ref] = 0
            elif r < 0.95:
                shares = rng.randint(1, 1000)
                bodies.append(replace(ref, next_ref, shares, mid + 100 * rng.randint(-40, 40), locate))
                live[ref] = 0
                live[next_ref] = shares
                next_ref += 4
            else:
                bodies.append(delete(next_ref + 4_000_000, locate))
            if live.get(ref) == 0:
                del live[ref]
    return bodies


@cocotb.test()
async def test_random_flow(dut):
    await start_clock(dut)
    bodies = random_flow(random.Random(11), 6000)
    await run_book(dut, bodies, 7, model.pick_base(P(20.00)), name="random")


@cocotb.test()
async def test_random_flow_with_gaps(dut):
    await start_clock(dut)
    bodies = random_flow(random.Random(12), 6000)
    await run_book(dut, bodies, 7, model.pick_base(P(20.00)), gap_chance=0.3, seed=5,
                   name="random with gaps")


def real_setup():
    path = os.environ["ITCH_FILE"]
    bodies = read_itch_file(path, int(os.environ["ITCH_LIMIT"]) if "ITCH_LIMIT" in os.environ else None)
    names = {v: k for k, v in model.directory(path).items()}
    return path, bodies, names


@cocotb.test(skip=not os.environ.get("ITCH_FILE"))
async def test_real_stocks(dut):
    path, bodies, names = real_setup()
    count = int(os.environ.get("BOOK_STOCKS", "5"))
    await start_clock(dut)
    for locate, _ in model.busiest(path).most_common(count):
        mine = [b for b in bodies if int.from_bytes(b[1:3], "big") == locate]
        base = model.pick_base(model.first_add_price(path, locate))
        await run_book(dut, mine, locate, base, name=names.get(locate, str(locate)))


@cocotb.test(skip=not os.environ.get("ITCH_FILE"))
async def test_real_full_stream(dut):
    path, bodies, names = real_setup()
    ticker, locate, base = model.setup(path, os.environ.get("STOCK"))
    await start_clock(dut)
    await run_book(dut, bodies, locate, base, name=f"{ticker} in full stream")
