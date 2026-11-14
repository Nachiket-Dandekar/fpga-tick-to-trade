import struct
import zlib

import cocotb
from cocotb.triggers import RisingEdge, ReadOnly, ClockCycles
from cocotb.utils import get_sim_time

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


def parse_order_frame(frame_info, expected_stock="UN      "):
    assert len(frame_info["nibbles"]) % 2 == 0, "odd number of nibbles in frame"
    assert frame_info["preamble"] == PREAMBLE, f"bad preamble {frame_info['preamble'].hex()}"
    body = frame_info["body"]
    fcs = frame_info["fcs"]
    assert len(body) + len(fcs) == 103, f"expected 103 bytes after SFD, got {len(body) + len(fcs)}"
    assert frame_info["crc_ok"], f"bad FCS {fcs.hex()}"

    assert body[0:6] == b"\xff\xff\xff\xff\xff\xff", f"bad dst mac {body[0:6].hex()}"
    assert body[6:12] == b"\x02\x00\x00\x00\x00\x01", f"bad src mac {body[6:12].hex()}"
    assert body[12:14] == b"\x08\x00", f"bad ethertype {body[12:14].hex()}"

    ip_hdr = body[14:34]
    ver_ihl, dscp, total_len, ident, flags_frag, ttl, proto, hdr_csum, src_ip, dst_ip = (
        struct.unpack(">BBHHHBBH4s4s", ip_hdr)
    )
    assert ver_ihl == 0x45, f"bad version/IHL 0x{ver_ihl:02x}"
    assert dscp == 0, f"bad dscp {dscp}"
    assert total_len == 85, f"bad ip total length {total_len}"
    assert ident == 0, f"bad ip id {ident}"
    assert flags_frag == 0x4000, f"bad flags/frag 0x{flags_frag:04x}"
    assert ttl == 64, f"bad ttl {ttl}"
    assert proto == 17, f"bad proto {proto}"
    assert src_ip == bytes([10, 0, 0, 2]), f"bad src ip {list(src_ip)}"
    assert dst_ip == bytes([10, 0, 0, 255]), f"bad dst ip {list(dst_ip)}"
    exp_csum = ip_checksum(ip_hdr[:10] + b"\x00\x00" + ip_hdr[12:])
    assert hdr_csum == exp_csum and ip_checksum(ip_hdr) == 0, (
        f"bad ip checksum 0x{hdr_csum:04x}, expected 0x{exp_csum:04x}"
    )

    udp_hdr = body[34:42]
    src_port, dst_port, udp_len, udp_csum = struct.unpack(">HHHH", udp_hdr)
    assert src_port == 26401, f"bad udp src port {src_port}"
    assert dst_port == 26401, f"bad udp dst port {dst_port}"
    assert udp_len == 65, f"bad udp length {udp_len}"
    assert udp_csum == 0, f"bad udp checksum {udp_csum}"

    payload = body[42:99]
    assert len(payload) == 57, f"bad payload length {len(payload)}"
    (msg_type, token, side, shares, stock, price, tif, firm,
     display, capacity, iso, min_qty, cross, cust, latency, msg_index) = struct.unpack(
        ">c14scI8sII4scccIccII", payload
    )
    token_str = token.decode("ascii")
    stock_str = stock.decode("ascii")
    assert msg_type == b"O", f"bad type {msg_type!r}"
    assert token_str.startswith("T2T000"), f"bad token prefix {token_str!r}"
    assert side == b"B", f"bad side {side!r}"
    assert stock_str == expected_stock.ljust(8)[:8], f"bad stock {stock_str!r}"
    assert tif == 0, f"bad tif {tif}"
    assert firm == b"T2T ", f"bad firm {firm!r}"
    assert display == b"N", f"bad display {display!r}"
    assert capacity == b"P", f"bad capacity {capacity!r}"
    assert iso == b"N", f"bad iso {iso!r}"
    assert min_qty == 0, f"bad min_qty {min_qty}"
    assert cross == b"N", f"bad cross {cross!r}"
    assert cust == b"N", f"bad customer {cust!r}"

    return {
        "order_num": int(token_str[6:], 16),
        "token": token_str,
        "shares": shares,
        "price": price,
        "stock": stock_str,
        "latency": latency,
        "msg_index": msg_index,
        "ifg_nibbles": frame_info["ifg_nibbles"],
        "start_ps": frame_info["start_ps"],
    }


class MiiMonitor:
    def __init__(self, dut, clk=None, tx_en=None, txd=None):
        self.clk = dut.tx_clk if clk is None else clk
        self.tx_en = dut.mii_tx_en if tx_en is None else tx_en
        self.txd = dut.mii_txd if txd is None else txd
        self.frames = []
        self._task = cocotb.start_soon(self._run())

    def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self):
        active = False
        cur_nibbles = []
        start_ps = 0
        idle_nibbles = 0
        seen_frame = False
        cur_ifg = None

        while True:
            if not active and (not seen_frame or idle_nibbles >= 64):
                await RisingEdge(self.tx_en)
                await ReadOnly()
            else:
                await RisingEdge(self.clk)
                await ReadOnly()
            en = int(self.tx_en.value) if self.tx_en.value.is_resolvable else 0
            d = int(self.txd.value) if self.txd.value.is_resolvable else 0

            if en == 1:
                if not active:
                    active = True
                    start_ps = get_sim_time("ps")
                    cur_ifg = idle_nibbles if seen_frame else None
                    cur_nibbles = [d]
                else:
                    cur_nibbles.append(d)
            else:
                if active:
                    raw = bytes(
                        cur_nibbles[i] | (cur_nibbles[i + 1] << 4)
                        for i in range(0, len(cur_nibbles) - 1, 2)
                    )
                    preamble = raw[:8]
                    body = raw[8:-4]
                    fcs = raw[-4:]
                    crc_ok = len(raw) >= 12 and fcs == struct.pack("<I", zlib.crc32(body))
                    self.frames.append({
                        "nibbles": list(cur_nibbles),
                        "raw": raw,
                        "preamble": preamble,
                        "body": body,
                        "fcs": fcs,
                        "crc_ok": crc_ok,
                        "ifg_nibbles": cur_ifg,
                        "start_ps": start_ps,
                    })
                    active = False
                    seen_frame = True
                    idle_nibbles = 1
                elif seen_frame:
                    idle_nibbles += 1
