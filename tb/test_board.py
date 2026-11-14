import os
import re
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles, Timer, with_timeout
from cocotb.utils import get_sim_time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import book as model
from expected import expected_fields, status_text
from replay import mold_packets
from strategy import run_strategy, pack_order_payload
from eth_frames import MiiDriver, MiiMonitor, parse_order_frame, udp_frame, with_fcs
from itch_msgs import add_order, val

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "itch_orders.bin")
SLICE_START = 10700
SLICE_LEN = 3000

CLK_NS = 10
SYS_NS = 10
CLKS_PER_BIT = 8
BIT_NS = CLKS_PER_BIT * SYS_NS
RESET_CLKS = 100 * 20

HEX8 = "[0-9A-F]{8}"
HEX4 = "[0-9A-F]{4}"
LINE = re.compile(
    f"ok=({HEX8}) crc=({HEX8}) drop=({HEX8}) gap=({HEX8}) ovf=({HEX8}) msg=({HEX8}) "
    f"max=({HEX4}) col=({HEX4}) oor=({HEX4}) "
    f"bid=([01]) ({HEX8}) ({HEX8}) ask=([01]) ({HEX8}) ({HEX8}) "
    f"ord=({HEX8}) odrop=({HEX8}) lat=({HEX8}) lmin=({HEX8}) lmax=({HEX8})$")
NAMES = ["ok", "crc", "drop", "gap", "ovf", "msg", "max", "col", "oor"]
ORDER_NAMES = ["ord", "odrop", "lat", "lmin", "lmax"]


def parse(line):
    m = LINE.match(line)
    assert m, f"bad status line: {line!r}"
    g = [int(x, 16) for x in m.groups()]
    fields = dict(zip(NAMES, g[:9]))
    fields["bid"] = tuple(g[9:12])
    fields["ask"] = tuple(g[12:15])
    fields.update(dict(zip(ORDER_NAMES, g[15:20])))
    return fields


async def uart_monitor(dut, lines):
    text = bytearray()
    while True:
        await FallingEdge(dut.uart_txd)
        await Timer(BIT_NS * 3 // 2, unit="ns")
        byte = 0
        for i in range(8):
            byte |= val(dut.uart_txd) << i
            await Timer(BIT_NS, unit="ns")
        assert val(dut.uart_txd) == 1, "missing stop bit"
        text.append(byte)
        if text.endswith(b"\r\n"):
            lines.append(text[:-2].decode())
            text = bytearray()


async def wait_ready(dut):
    while val(dut.rst):
        await RisingEdge(dut.clk_sys)
    await ClockCycles(dut.clk_sys, 4)
    while val(dut.eth.book.busy):
        await RisingEdge(dut.clk_sys)


async def next_lines(dut, lines, count):
    want = len(lines) + count
    while len(lines) < want:
        await ClockCycles(dut.clk_sys, 1000)
    return lines[-1]


async def drain(dut):
    eth = dut.eth
    for _ in range(1000):
        await ClockCycles(dut.clk_sys, 100)
        if (val(eth.rx_cross.empty) and not val(eth.fifo.level) and not val(eth.fifo.out_valid)
                and not val(eth.book.busy) and val(eth.tx_path.q_count) == 0
                and val(eth.tx_path.state) == 0 and val(eth.tx_path.tx_empty)):
            break
    await ClockCycles(dut.clk_sys, 20)


async def check_phy_reset(dut, timeout_us):
    assert val(dut.eth_rstn) == 0, "eth_rstn should be low"
    low_from = get_sim_time("ns")
    await with_timeout(RisingEdge(dut.eth_rstn), timeout_us, "us")
    low_ns = get_sim_time("ns") - low_from
    assert low_ns >= RESET_CLKS * SYS_NS, f"eth_rstn low for only {low_ns} ns"
    return low_ns


async def check_ref_clock(dut):
    await RisingEdge(dut.eth_ref_clk)
    times = []
    for _ in range(9):
        await RisingEdge(dut.eth_ref_clk)
        times.append(get_sim_time("ps"))
    periods = {b - a for a, b in zip(times, times[1:])}
    assert periods == {4 * CLK_NS * 1000}, f"eth_ref_clk periods {periods} ps"


def slice_bodies(locate, base):
    bodies = list(model.read_messages(DATA))[SLICE_START:SLICE_START + SLICE_LEN]
    ref = 1 << 40
    for k in range(6):
        bodies.append(add_order(ref + (k << 40), "B", 100, "UN", base + 100 * (5 + k), locate))
    for k in range(3):
        bodies.append(add_order(ref + 77 + k, "S", 100, "UN", base - 100 * (1 + k), locate))
    return bodies


def check_line(fields, exp, frames, parsed_orders, label):
    got = {k: fields[k] for k in ("msg", "col", "oor", "bid", "ask", "ord", "odrop")}
    assert got == {k: exp[k] for k in got}, f"{label}: board {got}, model {exp}"
    assert fields["ok"] == frames, f"{label}: ok={fields['ok']}, sent {frames} frames"
    for k in ("crc", "drop", "gap", "ovf"):
        assert fields[k] == 0, f"{label}: {k}={fields[k]}"
    if parsed_orders:
        lats = [o["latency"] for o in parsed_orders]
        assert fields["lat"] == lats[-1], f"{label}: lat={fields['lat']}, expected {lats[-1]}"
        assert fields["lmin"] == min(lats), f"{label}: lmin={fields['lmin']}, expected {min(lats)}"
        assert fields["lmax"] == max(lats), f"{label}: lmax={fields['lmax']}, expected {max(lats)}"


async def send_and_check(dut, mii, tx_mon, lines, frames, exp, exp_orders, label):
    tx_mon.frames.clear()
    for frame in frames:
        await mii.send(frame)
    await drain(dut)
    line = await next_lines(dut, lines, 2)
    fields = parse(line)
    dut._log.info(f"{label}: {line}")

    assert val(dut.eth.tx_underrun) == 0, f"{label}: tx_underrun asserted"
    assert len(tx_mon.frames) == len(exp_orders), (
        f"{label}: expected {len(exp_orders)} order frames, got {len(tx_mon.frames)}"
    )
    parsed_orders = []
    for idx, (frame_info, exp_o) in enumerate(zip(tx_mon.frames, exp_orders), 1):
        p = parse_order_frame(frame_info)
        parsed_orders.append(p)
        assert p["order_num"] == idx, f"{label}: order {idx} num {p['order_num']}"
        assert p["token"] == exp_o["token"], f"{label}: token {p['token']} != {exp_o['token']}"
        assert p["shares"] == exp_o["shares"], f"{label}: shares {p['shares']} != {exp_o['shares']}"
        assert p["price"] == exp_o["price"], f"{label}: price {p['price']} != {exp_o['price']}"
        assert p["msg_index"] == exp_o["msg_index"], (
            f"{label}: msg_index {p['msg_index']} != {exp_o['msg_index']}"
        )
        exp_payload = pack_order_payload(idx, exp_o["shares"], exp_o["price"], p["latency"], exp_o["msg_index"])
        assert frame_info["body"][42:99] == exp_payload

    check_line(fields, exp, len(frames), parsed_orders, label)
    bv, ask_valid = exp["bid"][0], exp["ask"][0]
    assert val(dut.led) & 0b0100 == (0b0100 if bv and ask_valid else 0)
    assert val(dut.led) & 0b1000 == 0, "error led is on"
    assert val(dut.led) & 0b0010, "frame led is off right after traffic"


async def check_zero(dut, lines, label):
    line = await next_lines(dut, lines, 2)
    fields = parse(line)
    dut._log.info(f"{label}: {line}")
    for k in NAMES + ORDER_NAMES:
        assert fields[k] == 0, f"{label}: {k}={fields[k]}"
    assert fields["bid"] == (0, 0, 0) and fields["ask"] == (0, 0, 0), f"{label}: {line}"


@cocotb.test()
async def test_board(dut):
    locate = int(dut.TARGET_LOCATE.value)
    base = int(dut.BASE_PRICE.value)
    ticker, want_locate, want_base = model.setup(DATA)
    assert (locate, base) == (want_locate, want_base), \
        f"top defaults {locate}/{base}, book.py gives {ticker} {want_locate}/{want_base}"

    dut.btn_rst.value = 0
    dut.eth_rxerr.value = 0
    dut.eth_col.value = 0
    dut.eth_crs.value = 0
    dut.eth_tx_clk.value = 0
    mii = MiiDriver(dut, clk=dut.eth_rx_clk, dv=dut.eth_rx_dv, rxd=dut.eth_rxd)
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await Timer(7.3, unit="ns")
    cocotb.start_soon(Clock(dut.eth_rx_clk, 40, unit="ns").start())
    await Timer(11.9, unit="ns")
    cocotb.start_soon(Clock(dut.eth_tx_clk, 40, unit="ns").start())
    tx_mon = MiiMonitor(dut, clk=dut.eth_tx_clk, tx_en=dut.eth_tx_en, txd=dut.eth_txd)
    lines = []
    cocotb.start_soon(uart_monitor(dut, lines))

    await Timer(50, unit="ns")
    low_ns = await check_phy_reset(dut, 200)
    await check_ref_clock(dut)
    await wait_ready(dut)
    dut._log.info(f"eth_rstn low for {low_ns} ns after power up, design out of reset at "
                  f"{get_sim_time('us'):.1f} us")
    await check_zero(dut, lines, "after power up")

    bodies = slice_bodies(locate, base)
    frames = [with_fcs(udp_frame(p)) for p in mold_packets(bodies)]
    exp = expected_fields(bodies, locate, base)
    _, exp_orders = run_strategy(bodies, locate, base)
    assert exp["col"] > 0 and exp["oor"] == 3 and len(exp_orders) > 0
    dut._log.info(f"model: {status_text(exp)}")
    await send_and_check(dut, mii, tx_mon, lines, frames, exp, exp_orders, f"{ticker} slice")

    dut.btn_rst.value = 1
    await ClockCycles(dut.clk_sys, 50)
    dut.btn_rst.value = 0
    await ClockCycles(dut.clk_sys, 2)
    low_ns = await check_phy_reset(dut, 200)
    await wait_ready(dut)
    dut._log.info(f"button: eth_rstn low for {low_ns} ns")
    await check_zero(dut, lines, "after button")

    await send_and_check(dut, mii, tx_mon, lines, frames, exp, exp_orders, f"{ticker} slice again")
