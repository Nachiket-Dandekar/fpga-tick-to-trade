import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, ClockCycles

from eth_frames import MiiDriver, PREAMBLE, MIN_IFG, nibbles, with_fcs
from itch_msgs import val


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    mii = MiiDriver(dut)
    dut.rst.value = 1
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)
    return mii


async def monitor(dut, frames):
    data = bytearray()
    starts = []
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        if val(dut.byte_valid):
            if val(dut.frame_start):
                starts.append(len(data))
            data.append(val(dut.byte_data))
        if val(dut.frame_end):
            frames.append((bytes(data), starts, val(dut.frame_crc_ok)))
            data = bytearray()
            starts = []


def flip_bit(frame, rng):
    bit = rng.randrange(len(frame) * 8)
    out = bytearray(frame)
    out[bit // 8] ^= 1 << (bit % 8)
    return bytes(out)


def check(dut, frames, sent):
    assert len(frames) == len(sent), f"expected {len(sent)} frames, got {len(frames)}"
    for i, ((data, starts, crc_ok), (exp, exp_ok)) in enumerate(zip(frames, sent)):
        assert data == exp, f"frame {i}: {len(data)} bytes received, {len(exp)} sent, data differs"
        assert starts == [0], f"frame {i}: frame_start at byte positions {starts}"
        assert crc_ok == exp_ok, f"frame {i}: frame_crc_ok {crc_ok}, expected {exp_ok}"
    bad = sum(1 for _, ok in sent if not ok)
    dut._log.info(f"{len(sent)} frames matched ({bad} with a flipped bit), "
                  f"{sum(len(e) for e, _ in sent)} bytes")


def random_length(rng):
    r = rng.random()
    if r < 0.4:
        return rng.randint(1, 64)
    if r < 0.8:
        return rng.randint(65, 300)
    return rng.randint(301, 1514)


@cocotb.test()
async def test_random_frames(dut):
    mii = await reset(dut)
    rng = random.Random(21)
    frames, sent = [], []
    cocotb.start_soon(monitor(dut, frames))
    for _ in range(300):
        frame = with_fcs(bytes(rng.getrandbits(8) for _ in range(random_length(rng))))
        good = rng.random() < 0.6
        if not good:
            frame = flip_bit(frame, rng)
        sent.append((frame, good))
        await mii.send(frame, ifg=rng.randint(1, 40))
    await ClockCycles(dut.clk, 5)
    check(dut, frames, sent)


@cocotb.test()
async def test_back_to_back_min_gap(dut):
    mii = await reset(dut)
    rng = random.Random(22)
    frames, sent = [], []
    cocotb.start_soon(monitor(dut, frames))
    for _ in range(200):
        frame = with_fcs(bytes(rng.getrandbits(8) for _ in range(rng.choice([60, 61, 64, 100, 1514]))))
        sent.append((frame, True))
        await mii.send(frame, ifg=MIN_IFG)
    await ClockCycles(dut.clk, 5)
    check(dut, frames, sent)


@cocotb.test()
async def test_bad_line_conditions(dut):
    mii = await reset(dut)
    rng = random.Random(23)
    frames, sent = [], []
    cocotb.start_soon(monitor(dut, frames))

    good = with_fcs(bytes(rng.getrandbits(8) for _ in range(80)))
    await mii.send_raw([0x3] + nibbles(PREAMBLE + good))
    await mii.send(good)
    sent.append((good, True))

    await mii.send_raw(nibbles(PREAMBLE + good) + [0x7])
    await mii.send(good)
    sent.append((good, True))

    await mii.send_raw(nibbles(PREAMBLE[:3]))
    await mii.send(good)
    sent.append((good, True))

    await ClockCycles(dut.clk, 5)
    assert len(frames) == 4, f"expected 4 frame_end pulses, got {len(frames)}"
    data, starts, crc_ok = frames.pop(1)
    assert data == good and crc_ok == 0, "frame with an odd trailing nibble must fail the CRC check"
    check(dut, frames, sent)
