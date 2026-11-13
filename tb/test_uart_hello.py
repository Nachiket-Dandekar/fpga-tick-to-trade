import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

from itch_msgs import val

MESSAGE = b"Hello from Arty\r\n"


async def read_byte(dut, clks_per_bit):
    await FallingEdge(dut.uart_txd)
    await ClockCycles(dut.clk, clks_per_bit // 2)
    assert val(dut.uart_txd) == 0, "start bit is not low"
    value = 0
    for bit in range(8):
        await ClockCycles(dut.clk, clks_per_bit)
        value |= val(dut.uart_txd) << bit
    await ClockCycles(dut.clk, clks_per_bit)
    assert val(dut.uart_txd) == 1, "stop bit is not high"
    return value


@cocotb.test()
async def test_hello_twice(dut):
    clks_per_bit = int(dut.CLKS_PER_BIT.value)
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    received = bytearray()
    for _ in range(2 * len(MESSAGE)):
        received.append(await read_byte(dut, clks_per_bit))
    assert bytes(received) == MESSAGE * 2, f"got {bytes(received)!r}"
    assert val(dut.led) == 2, f"led shows {val(dut.led)}, expected 2 messages"
    dut._log.info(f"received {bytes(received)!r}")
