#!/usr/bin/env python3
"""
powermeter_via_ip.py

Read real-time data from a Victron VM-3P75CT energy meter over Ethernet
(Modbus/UDP) using pymodbus.

Features
--------
- Reads total voltage, frequency, total power and total energy (forward/reverse)
- Reads per-phase voltage, current, active power (L1, L2, L3)
- Reads per-phase forward and reverse energy (L1, L2, L3)
- Computes cos φ (power factor) per phase and total, based on P, U, I
- Prints live values once per second

Requirements
-----------
- Python 3.x
- pymodbus 3.x or 4.x (new API)

Install (in your virtualenv):
    pip install "pymodbus>=3,<5"

Notes
-----
- The VM-3P75CT uses Modbus over UDP on port 502.
- There is no official public Modbus map, but community work
  (Home Assistant + Victron community) has established a stable map
  that this script follows.
"""

import time
from typing import Dict, List, Optional

from pymodbus.client import ModbusUdpClient

# ---------------------------------------------------------------------------
# Configuration parameters
# ---------------------------------------------------------------------------

#: IP address of your VM-3P75CT meter.
#: Replace this with your meter's actual IP address.
IP_ADDRESS: str = "192.168.0.155"

#: Modbus/UDP port used by VM-3P75CT.
#: Community examples and Victron docs indicate port 502.
PORT: int = 502

#: Modbus device ID of the meter.
#: For Ethernet/UDP devices on Victron, this is typically 1.
DEVICE_ID: int = 1


# ---------------------------------------------------------------------------
# Helper functions for numeric decoding
# ---------------------------------------------------------------------------

def _twos_complement(value: int, bits: int) -> int:
    """
    Convert an unsigned integer to a signed integer using two's complement.

    Parameters
    ----------
    value : int
        Raw integer value (e.g. from a Modbus register).
    bits : int
        Number of bits of the value (16 or 32).

    Returns
    -------
    int
        Signed integer representation.
    """
    if value & (1 << (bits - 1)):
        value -= 1 << bits
    return value


def decode_int16(registers: List[int], signed: bool = True) -> int:
    """
    Decode a 16-bit integer from a single Modbus register.

    Parameters
    ----------
    registers : list[int]
        A list of exactly one 16-bit register value as returned by pymodbus.
    signed : bool, optional
        If True, interpret the value as signed (two's complement). If False,
        interpret as unsigned. Default is True.

    Returns
    -------
    int
        Decoded 16-bit integer value.

    Raises
    ------
    ValueError
        If `registers` does not contain exactly one element.
    """
    if len(registers) != 1:
        raise ValueError("decode_int16 expects exactly 1 register")

    raw = registers[0] & 0xFFFF
    if signed:
        return _twos_complement(raw, 16)
    return raw


def decode_int32(registers: List[int], signed: bool = True) -> int:
    """
    Decode a 32-bit integer from two Modbus registers (big-endian word order).

    Parameters
    ----------
    registers : list[int]
        A list of exactly two 16-bit register values as returned by pymodbus.
        The first element is the high word, the second is the low word.
    signed : bool, optional
        If True, interpret the combined 32-bit value as signed. If False,
        interpret as unsigned. Default is True.

    Returns
    -------
    int
        Decoded 32-bit integer value.

    Raises
    ------
    ValueError
        If `registers` does not contain exactly two elements.
    """
    if len(registers) != 2:
        raise ValueError("decode_int32 expects exactly 2 registers")

    hi = registers[0] & 0xFFFF
    lo = registers[1] & 0xFFFF
    raw = (hi << 16) | lo
    if signed:
        return _twos_complement(raw, 32)
    return raw


# ---------------------------------------------------------------------------
# Modbus register reading helpers
# ---------------------------------------------------------------------------

def read_input_or_holding(
    client: ModbusUdpClient,
    address: int,
    count: int = 1,
) -> Optional[List[int]]:
    """
    Read a block of registers from the VM-3P75CT.

    This function tries Input Registers (function code 4) first, then
    falls back to Holding Registers (function code 3) if needed.

    Parameters
    ----------
    client : ModbusUdpClient
        An instance of the pymodbus UDP client, already connected.
    address : int
        Modbus register address to start reading from (0-based, hex in docs).
    count : int, optional
        Number of 16-bit registers to read. Default is 1.

    Returns
    -------
    list[int] or None
        If successful, returns a list of `count` register values (ints).
        If both reads fail, returns None.

    Notes
    -----
    - pymodbus 3.x stable uses parameter name `slave=DEVICE_ID`
    - pymodbus 4.x dev uses `device_id=DEVICE_ID`
    This script uses `device_id`. If you get "unexpected keyword 'device_id'",
    replace `device_id=DEVICE_ID` with `slave=DEVICE_ID` in the two calls below.
    """
    # Try Input Registers (function 4)
    rr = client.read_input_registers(
        address=address,
        count=count,
        device_id=DEVICE_ID,
    )
    if rr is not None and not rr.isError():
        return rr.registers

    # Fallback: Holding Registers (function 3)
    rr = client.read_holding_registers(
        address=address,
        count=count,
        device_id=DEVICE_ID,
    )
    if rr is not None and not rr.isError():
        return rr.registers

    return None


def read_int16_scaled(
    client: ModbusUdpClient,
    address: int,
    scale: float = 1.0,
    signed: bool = True,
) -> Optional[float]:
    """
    Read a 16-bit value from the meter and apply a linear scale.

    Parameters
    ----------
    client : ModbusUdpClient
        Connected Modbus/UDP client.
    address : int
        Modbus register address (0-based).
    scale : float, optional
        Multiplicative scaling factor (e.g. 0.01 to convert centi-units to units).
    signed : bool, optional
        If True, interpret the register as signed; otherwise as unsigned.

    Returns
    -------
    float or None
        Scaled floating-point value, or None if reading failed.
    """
    regs = read_input_or_holding(client, address, count=1)
    if regs is None:
        return None

    raw = decode_int16(regs, signed=signed)
    return raw * scale


def read_int32_scaled(
    client: ModbusUdpClient,
    address: int,
    scale: float = 1.0,
    signed: bool = True,
) -> Optional[float]:
    """
    Read a 32-bit value from the meter and apply a linear scale.

    Parameters
    ----------
    client : ModbusUdpClient
        Connected Modbus/UDP client.
    address : int
        Start address of the 32-bit value (two consecutive registers).
    scale : float, optional
        Multiplicative scaling factor (e.g. 0.01 for kWh).
    signed : bool, optional
        If True, interpret the combined 32-bit value as signed.

    Returns
    -------
    float or None
        Scaled floating-point value, or None if reading failed.
    """
    regs = read_input_or_holding(client, address, count=2)
    if regs is None:
        return None

    raw = decode_int32(regs, signed=signed)
    return raw * scale


# ---------------------------------------------------------------------------
# Core data acquisition: read_all() + power factor computation
# ---------------------------------------------------------------------------

def read_all(client: ModbusUdpClient) -> Dict[str, Optional[float]]:
    """
    Read a set of useful measurements from the VM-3P75CT.

    Register addresses & scales are based on:
    - Home Assistant VM-3P75CT Modbus config (Kerbal / FVBH) :contentReference[oaicite:2]{index=2}

    Values read
    -----------
    - Total active power (W)
    - Total forward and reverse energy (kWh)
    - Grid frequency (Hz) and PEN voltage (V)
    - Per-phase voltage, current, active power (L1, L2, L3)
    - Per-phase forward and reverse energy (kWh) L1, L2, L3
    - Computed cos φ (power factor) per phase and total

    Parameters
    ----------
    client : ModbusUdpClient
        Connected Modbus/UDP client.

    Returns
    -------
    dict[str, float or None]
        Mapping of measurement names to values (floats). Values are None if
        the underlying Modbus read failed.
    """
    data: Dict[str, Optional[float]] = {}

    # --------- Sum / system-wide values --------- #
    # Total active power (W), signed 32-bit at 0x3080
    data["P_total_W"] = read_int32_scaled(client, 0x3080, scale=1.0, signed=True)

    # Total forward energy (kWh), unsigned 32-bit, 0.01 scale at 0x3034
    data["E_total_forward_kWh"] = read_int32_scaled(
        client, 0x3034, scale=0.01, signed=False
    )

    # Total reverse energy (kWh), unsigned 32-bit, 0.01 scale at 0x3036
    data["E_total_reverse_kWh"] = read_int32_scaled(
        client, 0x3036, scale=0.01, signed=False
    )

    # PEN voltage (V), signed 16-bit, 0.01 scale at 0x3033
    data["U_PEN_V"] = read_int16_scaled(client, 0x3033, scale=0.01, signed=True)

    # Grid frequency (Hz), unsigned 16-bit, 0.01 scale at 0x3032
    data["freq_Hz"] = read_int16_scaled(client, 0x3032, scale=0.01, signed=False)

    # --------- Phase L1 --------- #
    # Base block L1 around 0x3040.
    data["U_L1_V"] = read_int16_scaled(client, 0x3040, scale=0.01, signed=True)
    data["I_L1_A"] = read_int16_scaled(client, 0x3041, scale=0.01, signed=True)
    # L1 active power (W), signed 32-bit at 0x3082
    data["P_L1_W"] = read_int32_scaled(client, 0x3082, scale=1.0, signed=True)

    # L1 forward energy (kWh), uint32 at 0x3042/0x3043, scale 0.01  (comment in HA config)
    data["E_L1_forward_kWh"] = read_int32_scaled(
        client, 0x3042, scale=0.01, signed=False
    )

    # L1 reverse energy (kWh), uint32 at 0x3044/0x3045, scale 0.01
    data["E_L1_reverse_kWh"] = read_int32_scaled(
        client, 0x3044, scale=0.01, signed=False
    )

    # --------- Phase L2 --------- #
    data["U_L2_V"] = read_int16_scaled(client, 0x3048, scale=0.01, signed=True)
    data["I_L2_A"] = read_int16_scaled(client, 0x3049, scale=0.01, signed=True)
    # L2 active power (W), signed 32-bit at 0x3086
    data["P_L2_W"] = read_int32_scaled(client, 0x3086, scale=1.0, signed=True)

    # L2 forward energy (kWh), uint32 at 0x304A/0x304B, scale 0.01
    data["E_L2_forward_kWh"] = read_int32_scaled(
        client, 0x304A, scale=0.01, signed=False
    )

    # L2 reverse energy (kWh), uint32 at 0x304C/0x304D, scale 0.01
    data["E_L2_reverse_kWh"] = read_int32_scaled(
        client, 0x304C, scale=0.01, signed=False
    )

    # --------- Phase L3 --------- #
    data["U_L3_V"] = read_int16_scaled(client, 0x3050, scale=0.01, signed=True)
    data["I_L3_A"] = read_int16_scaled(client, 0x3051, scale=0.01, signed=True)
    # L3 active power (W), signed 32-bit at 0x308A
    data["P_L3_W"] = read_int32_scaled(client, 0x308A, scale=1.0, signed=True)

    # L3 forward energy (kWh), uint32 at 0x3052/0x3053, scale 0.01
    data["E_L3_forward_kWh"] = read_int32_scaled(
        client, 0x3052, scale=0.01, signed=False
    )

    # L3 reverse energy (kWh), uint32 at 0x3054/0x3055, scale 0.01
    data["E_L3_reverse_kWh"] = read_int32_scaled(
        client, 0x3054, scale=0.01, signed=False
    )

    # --------- Derived values: power factor (cos φ) --------- #
    # For each phase:
    #   cos φ_phase = P_phase / (U_phase * I_phase)
    # For total:
    #   S_total = sum(|U_phase * I_phase|)
    #   cos φ_total = P_total / S_total
    # Values are clipped to [-1.0, 1.0].

    def _pf_for_phase(P: Optional[float], U: Optional[float], I: Optional[float]) -> Optional[float]:
        if P is None or U is None or I is None:
            return None
        denom = U * I
        if abs(denom) < 1e-6:
            return None
        pf = P / denom
        if pf > 1.0:
            pf = 1.0
        if pf < -1.0:
            pf = -1.0
        return pf

    # Per-phase PF
    data["PF_L1"] = _pf_for_phase(data["P_L1_W"], data["U_L1_V"], data["I_L1_A"])
    data["PF_L2"] = _pf_for_phase(data["P_L2_W"], data["U_L2_V"], data["I_L2_A"])
    data["PF_L3"] = _pf_for_phase(data["P_L3_W"], data["U_L3_V"], data["I_L3_A"])

    # Total PF
    P_total = data["P_total_W"]
    if P_total is None:
        data["PF_total"] = None
    else:
        S_terms = []
        for phase in ("L1", "L2", "L3"):
            U = data.get(f"U_{phase}_V")
            I = data.get(f"I_{phase}_A")
            if U is not None and I is not None:
                S_terms.append(abs(U * I))

        S_total = sum(S_terms) if S_terms else 0.0
        if S_total <= 1e-6:
            data["PF_total"] = None
        else:
            pf_total = P_total / S_total
            if pf_total > 1.0:
                pf_total = 1.0
            if pf_total < -1.0:
                pf_total = -1.0
            data["PF_total"] = pf_total

    return data


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Main entry point.

    Creates a ModbusUdpClient, connects to the VM-3P75CT and prints a
    live snapshot of all measurements once per second until interrupted.
    """
    client = ModbusUdpClient(IP_ADDRESS, port=PORT)

    # Establish UDP connection to the meter.
    if not client.connect():
        print(f"Could not connect to VM-3P75CT at {IP_ADDRESS}:{PORT}")
        print("Check IP address, cabling, and that the meter is powered.")
        return

    try:
        while True:
            values = read_all(client)

            # If we cannot even read total power, assume something is wrong.
            if values.get("P_total_W") is None:
                print("Read error: could not read basic registers. "
                      "Check Modbus settings, device ID, and that "
                      "no other Modbus master is using the meter.")
            else:
                print("----- VM-3P75CT (Modbus/UDP live data) -----")
                print(f"Total active power:        {values['P_total_W']:.1f} W")
                print(
                    f"Total energy forward:      {values['E_total_forward_kWh']:.2f} kWh, "
                    f"reverse: {values['E_total_reverse_kWh']:.2f} kWh"
                )
                print(f"Frequency:                 {values['freq_Hz']:.2f} Hz")
                print(f"PEN voltage:               {values['U_PEN_V']:.1f} V")

                # Phase L1
                print(
                    f"L1: U={values['U_L1_V']:.1f} V, "
                    f"I={values['I_L1_A']:.3f} A, "
                    f"P={values['P_L1_W']:.1f} W, "
                    f"cos φ={values['PF_L1']:.3f}"
                    if values["PF_L1"] is not None
                    else f"L1: U={values['U_L1_V']:.1f} V, "
                         f"I={values['I_L1_A']:.3f} A, "
                         f"P={values['P_L1_W']:.1f} W, "
                         "cos φ=NA"
                )
                print(
                    f"    Energy L1 forward:     {values['E_L1_forward_kWh']:.2f} kWh, "
                    f"reverse: {values['E_L1_reverse_kWh']:.2f} kWh"
                )

                # Phase L2
                print(
                    f"L2: U={values['U_L2_V']:.1f} V, "
                    f"I={values['I_L2_A']:.3f} A, "
                    f"P={values['P_L2_W']:.1f} W, "
                    f"cos φ={values['PF_L2']:.3f}"
                    if values["PF_L2"] is not None
                    else f"L2: U={values['U_L2_V']:.1f} V, "
                         f"I={values['I_L2_A']:.3f} A, "
                         f"P={values['P_L2_W']:.1f} W, "
                         "cos φ=NA"
                )
                print(
                    f"    Energy L2 forward:     {values['E_L2_forward_kWh']:.2f} kWh, "
                    f"reverse: {values['E_L2_reverse_kWh']:.2f} kWh"
                )

                # Phase L3
                print(
                    f"L3: U={values['U_L3_V']:.1f} V, "
                    f"I={values['I_L3_A']:.3f} A, "
                    f"P={values['P_L3_W']:.1f} W, "
                    f"cos φ={values['PF_L3']:.3f}"
                    if values["PF_L3"] is not None
                    else f"L3: U={values['U_L3_V']:.1f} V, "
                         f"I={values['I_L3_A']:.3f} A, "
                         f"P={values['P_L3_W']:.1f} W, "
                         "cos φ=NA"
                )
                print(
                    f"    Energy L3 forward:     {values['E_L3_forward_kWh']:.2f} kWh, "
                    f"reverse: {values['E_L3_reverse_kWh']:.2f} kWh"
                )

                if values["PF_total"] is not None:
                    print(f"Total power factor:        {values['PF_total']:.3f}")
                else:
                    print("Total power factor:        NA")

                print()

            # Recommended polling interval: 0.5–1.0 s for this meter.
            time.sleep(1.0)

    finally:
        client.close()


if __name__ == "__main__":
    main()
