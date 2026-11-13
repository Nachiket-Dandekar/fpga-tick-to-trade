import struct
import zlib

from cocotb.triggers import RisingEdge, ClockCycles

PREAMBLE = b"\x55" * 7 + b"\xd5"
MIN_FRAME = 60
MIN_IFG = 24
UDP_PORT = 26400
DST_MAC = b"\xff" * 6
SRC_MAC = bytes.fromhex("b827eb123456")
SRC_IP = bytes([192, 168, 1, 50])
DST_IP = bytes([255, 255, 255, 255])


def ip_checksum(header):
    total = sum(struct.unpack(f">{len(header) // 2}H", header))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def udp_frame(payload, dst_port=UDP_PORT, ethertype=0x0800, protocol=17, version_ihl=0x45,
              udp_length=None, pad_to=MIN_FRAME):
    if udp_length is None:
        udp_length = 8 + len(payload)
    udp = struct.pack(">HHHH", 40000, dst_port, udp_length, 0) + payload
    options = b"\x00" * (4 * ((version_ihl & 0xF) - 5))
    ip = struct.pack(">BBHHHBBH4s4s", version_ihl, 0, 20 + len(options) + len(udp), 0, 0x4000,
                     64, protocol, 0, SRC_IP, DST_IP) + options
    ip = ip[:10] + struct.pack(">H", ip_checksum(ip)) + ip[12:]
    frame = DST_MAC + SRC_MAC + struct.pack(">H", ethertype) + ip + udp
    return frame.ljust(pad_to, b"\x00")


def with_fcs(frame):
    return frame + struct.pack("<I", zlib.crc32(frame))


def nibbles(data):
    out = []
    for b in data:
        out.append(b & 0xF)
        out.append(b >> 4)
    return out


class MiiDriver:
    def __init__(self, dut, clk=None, dv=None, rxd=None):
        self.clk = dut.clk if clk is None else clk
        self.dv = dut.mii_rx_dv if dv is None else dv
        self.rxd = dut.mii_rxd if rxd is None else rxd
        self.dv.value = 0
        self.rxd.value = 0

    async def send(self, frame, ifg=MIN_IFG):
        await self.send_raw(nibbles(PREAMBLE + frame), ifg)

    async def send_raw(self, nibble_list, ifg=MIN_IFG):
        edge = RisingEdge(self.clk)
        self.dv.value = 1
        for n in nibble_list:
            self.rxd.value = n
            await edge
        self.dv.value = 0
        self.rxd.value = 0
        await ClockCycles(self.clk, ifg)
