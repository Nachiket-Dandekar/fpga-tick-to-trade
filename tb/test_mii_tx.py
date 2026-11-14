import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, ClockCycles, Timer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from strategy import pack_order_payload
from eth_frames import MiiMonitor, parse_order_frame
from itch_msgs import val


async def cycle_counter_driver(dut):
    cnt = 0
    dut.cycle_cnt.value = 0
    while True:
        await RisingEdge(dut.clk)
        if val(dut.rst):
            cnt = 0
        else:
            cnt = (cnt + 1) & 0xFFFFFF
        dut.cycle_cnt.value = cnt


async def start_clocks_and_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 9.4, unit="ns").start())
    await Timer(3.2, unit="ns")
    cocotb.start_soon(Clock(dut.tx_clk, 39.6, unit="ns").start())
    cocotb.start_soon(cycle_counter_driver(dut))

    dut.rst.value = 1
    dut.order_valid.value = 0
    dut.order_price.value = 0
    dut.order_shares.value = 0
    dut.order_stamp.value = 0
    dut.order_msg_idx.value = 0
    await ClockCycles(dut.clk, 20)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 20)


async def wait_tx_idle(dut, expected_frames, mon):
    for _ in range(4000):
        await ClockCycles(dut.clk, 50)
        if len(mon.frames) >= expected_frames and val(dut.state) == 0 and val(dut.q_count) == 0:
            break
    await ClockCycles(dut.tx_clk, 10)


@cocotb.test()
async def test_single_and_back_to_back_frames(dut):
    await start_clocks_and_reset(dut)
    mon = MiiMonitor(dut, clk=dut.tx_clk, tx_en=dut.mii_tx_en, txd=dut.mii_txd)

    t_outs = []

    async def watch_t_out():
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            if val(dut.tx_wr_en) and val(dut.byte_idx) == 0:
                t_outs.append(val(dut.cycle_cnt))

    watcher = cocotb.start_soon(watch_t_out())

    orders_in = [
        (374_500, 100, 50, 12),
        (374_400, 250, 120, 45),
        (374_300, 500, 130, 88),
        (374_200, 75, 140, 103),
    ]

    await RisingEdge(dut.clk)
    p0, s0, st0, m0 = orders_in[0]
    dut.order_valid.value = 1
    dut.order_price.value = p0
    dut.order_shares.value = s0
    dut.order_stamp.value = st0
    dut.order_msg_idx.value = m0
    await RisingEdge(dut.clk)
    dut.order_valid.value = 0

    await wait_tx_idle(dut, 1, mon)

    for p, s, st, m in orders_in[1:]:
        dut.order_valid.value = 1
        dut.order_price.value = p
        dut.order_shares.value = s
        dut.order_stamp.value = st
        dut.order_msg_idx.value = m
        await RisingEdge(dut.clk)
    dut.order_valid.value = 0

    await wait_tx_idle(dut, 4, mon)
    watcher.cancel()
    mon.stop()

    assert len(mon.frames) == 4, f"expected 4 frames, got {len(mon.frames)}"
    assert val(dut.tx_underrun) == 0, "tx_underrun asserted"
    assert val(dut.orders_sent) == 4, f"orders_sent {val(dut.orders_sent)}"
    assert val(dut.orders_dropped) == 0, f"orders_dropped {val(dut.orders_dropped)}"

    lats = []
    for idx, (frame_info, (exp_p, exp_s, exp_st, exp_m)) in enumerate(zip(mon.frames, orders_in), 1):
        parsed = parse_order_frame(frame_info)
        exp_lat = (t_outs[idx - 1] - exp_st) & 0xFFFFFF
        lats.append(parsed["latency"])
        assert parsed["order_num"] == idx, f"order_num {parsed['order_num']} != {idx}"
        assert parsed["token"] == f"T2T000{idx:08X}"
        assert parsed["price"] == exp_p
        assert parsed["shares"] == exp_s
        assert parsed["msg_index"] == exp_m
        assert parsed["latency"] == exp_lat, f"latency {parsed['latency']} != {exp_lat}"
        exp_payload = pack_order_payload(idx, exp_s, exp_p, exp_lat, exp_m)
        assert frame_info["body"][42:99] == exp_payload
        if idx > 2:
            assert parsed["ifg_nibbles"] >= 24, (
                f"frame {idx} idle gap {parsed['ifg_nibbles']} nibbles (< 24 nibbles / 12 bytes)"
            )

    assert val(dut.last_latency) == lats[-1]
    assert val(dut.min_latency) == min(lats)
    assert val(dut.max_latency) == max(lats)


@cocotb.test()
async def test_queue_overflow_drops_and_counts(dut):
    await start_clocks_and_reset(dut)
    mon = MiiMonitor(dut, clk=dut.tx_clk, tx_en=dut.mii_tx_en, txd=dut.mii_txd)

    await RisingEdge(dut.clk)
    total_pushed = 21
    for i in range(total_pushed):
        dut.order_valid.value = 1
        dut.order_price.value = 300_000 + i * 100
        dut.order_shares.value = 10 + i
        dut.order_stamp.value = (val(dut.cycle_cnt) - 5) & 0xFFFFFF
        dut.order_msg_idx.value = i + 1
        await RisingEdge(dut.clk)
    dut.order_valid.value = 0

    await wait_tx_idle(dut, 17, mon)
    mon.stop()

    assert val(dut.tx_underrun) == 0, "tx_underrun asserted"
    assert val(dut.orders_sent) == 17, f"expected 17 orders sent, got {val(dut.orders_sent)}"
    assert val(dut.orders_dropped) == 4, f"expected 4 orders dropped, got {val(dut.orders_dropped)}"
    assert len(mon.frames) == 17, f"expected 17 frames on wire, got {len(mon.frames)}"

    for idx, frame_info in enumerate(mon.frames, 1):
        parsed = parse_order_frame(frame_info)
        assert parsed["order_num"] == idx
        assert parsed["price"] == 300_000 + (idx - 1) * 100
        assert parsed["shares"] == 10 + (idx - 1)
        assert parsed["msg_index"] == idx
        if idx > 1:
            assert parsed["ifg_nibbles"] >= 24, (
                f"frame {idx} idle gap {parsed['ifg_nibbles']} nibbles (< 24)"
            )
