"""
SunSpec Alliance Modbus TCP Register Mapping for Inverters and BESS Controllers.
"""

from typing import Dict, Any


class SunSpecInverterMapper:
    """
    Encodes and decodes standard SunSpec 700-series (Energy Storage Model) registers.
    """

    REGISTER_MAP = {
        40083: "WMaxLimPct",     # uint16: Scale factor applied to nominal active power
        40084: "StorCtl_Mod",    # bitfield16: 0=Disabled, 1=Charge, 2=Discharge, 3=Auto
        40085: "SetW",           # int16: Real power setpoint (kW or % scale)
        40086: "MinReservePct",  # uint16: Minimum backup reserve SoC percentage
    }

    @classmethod
    def encode_command(
        cls,
        active_power_limit_pct: float,
        mode: str,
        setpoint_kw: float,
        min_reserve_pct: float = 15.0,
    ) -> Dict[int, int]:
        """
        Translates high-level dispatch instructions into Modbus holding register 16-bit words.
        """
        # 40083: Power Limit (0 to 10000 = 0.00% to 100.00%)
        lim_reg = int(max(0.0, min(100.0, active_power_limit_pct)) * 100.0)

        # 40084: Mode
        mode_val = 0
        if mode == "CHARGE":
            mode_val = 1
        elif mode == "DISCHARGE":
            mode_val = 2
        elif mode == "AUTO":
            mode_val = 3

        # 40085: Setpoint kW (signed 16-bit integer, clamp to -32768 to 32767)
        sp_reg = int(max(-32000.0, min(32000.0, setpoint_kw))) & 0xFFFF

        # 40086: Reserve
        res_reg = int(max(0.0, min(100.0, min_reserve_pct)) * 100.0)

        return {
            40083: lim_reg,
            40084: mode_val,
            40085: sp_reg,
            40086: res_reg,
        }

    @classmethod
    def decode_registers(cls, register_values: Dict[int, int]) -> Dict[str, Any]:
        lim_pct = register_values.get(40083, 10000) / 100.0
        mode_int = register_values.get(40084, 0)
        mode_str = {0: "DISABLED", 1: "CHARGE", 2: "DISCHARGE", 3: "AUTO"}.get(mode_int, "UNKNOWN")

        sp_raw = register_values.get(40085, 0)
        # Convert unsigned 16-bit to signed
        if sp_raw > 32767:
            sp_raw -= 65536

        reserve_pct = register_values.get(40086, 1500) / 100.0

        return {
            "active_power_limit_pct": lim_pct,
            "storage_mode": mode_str,
            "setpoint_kw": float(sp_raw),
            "min_reserve_pct": reserve_pct,
        }

    @classmethod
    def build_modbus_tcp_write_frame(
        cls,
        registers: Dict[int, int],
        unit_id: int = 1,
        transaction_id: int = 1,
    ) -> bytes:
        """
        Encodes holding registers into a compliant Modbus TCP ADU
        (Function Code 0x10: Write Multiple Holding Registers).
        Header: [Transaction ID (2B)][Protocol ID 0x0000 (2B)][Length (2B)][Unit ID (1B)]
        PDU:    [FC 0x10 (1B)][Starting Address (2B)][Quantity of Registers (2B)][Byte Count (1B)][Register Values (2*N B)]
        """
        import struct

        sorted_addrs = sorted(registers.keys())
        if not sorted_addrs:
            raise ValueError("No registers provided for Modbus frame construction.")

        start_addr = sorted_addrs[0]
        # Modbus protocol addresses are 0-indexed offset from 40001
        start_offset = start_addr - 40001 if start_addr >= 40001 else start_addr
        qty = len(sorted_addrs)
        byte_count = qty * 2

        pdu = struct.pack(">BHHB", 0x10, start_offset, qty, byte_count)
        for addr in sorted_addrs:
            pdu += struct.pack(">H", registers[addr] & 0xFFFF)

        # MBAP Header: TransactionID (2B), ProtocolID (2B, always 0), Length (2B, 1B unit_id + len(pdu)), UnitID (1B)
        mbap_len = len(pdu) + 1
        mbap = struct.pack(">HHHB", transaction_id, 0x0000, mbap_len, unit_id)

        return mbap + pdu

    @classmethod
    def parse_modbus_tcp_response(cls, response_bytes: bytes) -> Dict[str, Any]:
        """
        Parses and validates a standard Modbus TCP response frame.
        """
        import struct

        if len(response_bytes) < 12:
            raise ValueError(f"Modbus response too short ({len(response_bytes)} bytes, expected >= 12)")

        trans_id, proto_id, length, unit_id, fc = struct.unpack(">HHHBB", response_bytes[:8])
        if fc & 0x80:
            exc_code = response_bytes[8]
            raise ValueError(f"Modbus Exception Response: Function Code 0x{fc:02X}, Exception Code {exc_code}")

        start_offset, qty = struct.unpack(">HH", response_bytes[8:12])
        return {
            "transaction_id": trans_id,
            "unit_id": unit_id,
            "function_code": fc,
            "starting_address": start_offset + 40001,
            "quantity": qty,
        }

