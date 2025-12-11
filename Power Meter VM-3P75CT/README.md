# Victron VM-3P75CT Modbus/UDP Reader

This repository contains a single Python script, `powermeter_via_ip.py`, which reads real‑time data from a **Victron VM‑3P75CT** three‑phase energy meter over **Ethernet (Modbus/UDP)** using the `pymodbus` library.

The script is intended as a simple CLI tool and reference implementation you can adapt for your own automation, logging, or integration with other systems.

---

## Features

- Connects to a VM‑3P75CT meter over **Modbus/UDP** (port `502` by default).
- Reads **system‑wide values**:
  - Total active power (W)
  - Total forward energy (kWh)
  - Total reverse energy (kWh)
  - PEN voltage (V)
  - Grid frequency (Hz)
- Reads **per‑phase values** (L1, L2, L3):
  - Phase voltage (V)
  - Phase current (A)
  - Phase active power (W)
  - Phase forward energy (kWh)
  - Phase reverse energy (kWh)
- **Computes power factor (cos φ)**:
  - Per phase: `PF_L1`, `PF_L2`, `PF_L3`
  - Total: `PF_total`
- Prints a **live snapshot once per second**:
  - Suitable for quick inspection or piping into other tools.

---

## Requirements

- **Python**: 3.x (tested with modern Python 3 versions)
- **Python packages**:
  - `pymodbus>=3,<5`

Install dependencies inside your virtual environment (recommended):

```bash
python -m venv .venv
. .venv/Scripts/activate  # PowerShell: .venv\Scripts\Activate.ps1
pip install "pymodbus>=3,<5"
```

On Windows PowerShell specifically:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install "pymodbus>=3,<5"
```

> Note: The script uses the **newer `pymodbus` API**. If you encounter errors about `device_id` vs `slave`, see the compatibility note below.

---

## Configuration

Configuration is done via module‑level constants at the top of `powermeter_via_ip.py`:

```python
IP_ADDRESS: str = "192.168.0.155"  # Set this to your meter's IP
PORT: int = 502                    # Modbus/UDP port (usually 502)
DEVICE_ID: int = 1                 # Modbus device ID (typically 1)
```

### 1. Set the meter IP address

Edit `IP_ADDRESS` to match the IP address of your VM‑3P75CT on your network. For example:

```python
IP_ADDRESS = "192.168.1.50"
```

### 2. Confirm port and device ID

- **PORT**: The VM‑3P75CT uses Modbus over UDP on port **502** in most setups.
- **DEVICE_ID**: For Ethernet/UDP Victron devices, the Modbus device ID is typically **1**.

Change these only if your installation differs.

---

## Usage

1. Ensure the VM‑3P75CT is powered and reachable from your machine.
2. Ensure the IP address and other settings in `powermeter_via_ip.py` are correct.
3. Activate your virtual environment (if using one).
4. Run the script from the repository root:

```powershell
cd z:\Pannsystem\Victron_py
python powermeter_via_ip.py
```

If `python` is mapped differently on your system, you can also try:

```powershell
py powermeter_via_ip.py
```

### What you’ll see

Once running, the script will output a block like this every second (example only):

```text
----- VM-3P75CT (Modbus/UDP live data) -----
Total active power:        1234.5 W
Total energy forward:      56.78 kWh, reverse: 0.12 kWh
Frequency:                 49.98 Hz
PEN voltage:               230.1 V
L1: U=230.1 V, I= 5.123 A, P=1170.0 W, cos φ=0.987
    Energy L1 forward:     12.34 kWh, reverse: 0.00 kWh
L2: U=229.8 V, I= 0.456 A, P= 104.7 W, cos φ=0.923
    Energy L2 forward:     10.23 kWh, reverse: 0.00 kWh
L3: U=230.3 V, I= 0.321 A, P=  73.9 W, cos φ=0.912
    Energy L3 forward:     34.56 kWh, reverse: 0.00 kWh
Total power factor:        0.975
```

Press `Ctrl+C` to stop the script.

---

## Data Model and Computations

The script uses helper functions to decode and scale values from Modbus registers:

- `decode_int16` / `decode_int32` convert raw Modbus registers (16‑bit / 32‑bit) to signed or unsigned integers using two’s complement where appropriate.
- `read_int16_scaled` / `read_int32_scaled` read one or two registers and apply linear scaling, e.g. `0.01` for centi‑units or 0.01 kWh.

All the main measurements are collected by the `read_all(client)` function, which returns a dictionary mapping keys to `float` values (or `None` if a read failed).

### Power factor (cos φ)

Power factor is computed from voltage, current, and active power:

- **Per phase** (L1, L2, L3):

  ```text
  PF_phase = P_phase / (U_phase * I_phase)
  ```

  Values are clipped to the range **[-1.0, 1.0]** and set to `None` if voltage or current is invalid or too close to zero.

- **Total**:

  ```text
  S_total = |U_L1 * I_L1| + |U_L2 * I_L2| + |U_L3 * I_L3|
  PF_total = P_total / S_total
  ```

  Again, the result is clipped to **[-1.0, 1.0]** and set to `None` if `S_total` is effectively zero or total power is unavailable.

These computed values are printed as `cos φ` per phase and `Total power factor` for the overall system.

---

## Modbus Register Access

The helper `read_input_or_holding` abstracts reading Input Registers (function code 4) and, if needed, falls back to Holding Registers (function code 3).

Key points:

- It uses the `ModbusUdpClient` from `pymodbus.client`.
- It first tries `read_input_registers(...)` and, if that fails or returns an error, it tries `read_holding_registers(...)`.
- Both calls pass `device_id=DEVICE_ID` by default, which is compatible with `pymodbus` 4.x.

### Compatibility note: `device_id` vs `slave`

Depending on the `pymodbus` version, the keyword argument for the unit/slave ID may differ:

- **pymodbus 3.x stable**: uses `slave=DEVICE_ID`
- **pymodbus 4.x dev / newer**: uses `device_id=DEVICE_ID`

If you see an error like:

> `TypeError: read_input_registers() got an unexpected keyword argument 'device_id'`

then modify the calls inside `read_input_or_holding` in `powermeter_via_ip.py` to use `slave=DEVICE_ID` instead of `device_id=DEVICE_ID`.

---

## Modbus Registers Used by This Script

The script currently uses a subset of the VM‑3P75CT Modbus map. All addresses below are **0‑based** and are shown in both **hex** and **decimal**. Types and scales match the helper calls in `read_all(client)`.

> This list documents only what the script actually reads. The physical meter supports more registers than are described here.

### System / Total Values

| Key                      | Addr (hex) | Addr (dec) | Size (regs) | Type        | Scale   | Description                              |
|--------------------------|-----------:|-----------:|------------:|------------|--------:|------------------------------------------|
| `P_total_W`              |   `0x3080` |      12416 |           2 | int32      |   1.00 | Total active power (W), signed           |
| `E_total_forward_kWh`   |   `0x3034` |      12340 |           2 | uint32     |   0.01 | Total forward energy (kWh)               |
| `E_total_reverse_kWh`   |   `0x3036` |      12342 |           2 | uint32     |   0.01 | Total reverse energy (kWh)               |
| `U_PEN_V`                |   `0x3033` |      12339 |           1 | int16      |   0.01 | PEN voltage (V)                           |
| `freq_Hz`                |   `0x3032` |      12338 |           1 | uint16     |   0.01 | Grid frequency (Hz)                       |

### Phase L1 Values

| Key                      | Addr (hex) | Addr (dec) | Size (regs) | Type        | Scale   | Description                              |
|--------------------------|-----------:|-----------:|------------:|------------|--------:|------------------------------------------|
| `U_L1_V`                 |   `0x3040` |      12352 |           1 | int16      |   0.01 | L1 phase‑to‑neutral voltage (V)          |
| `I_L1_A`                 |   `0x3041` |      12353 |           1 | int16      |   0.01 | L1 current (A)                            |
| `P_L1_W`                 |   `0x3082` |      12418 |           2 | int32      |   1.00 | L1 active power (W), signed              |
| `E_L1_forward_kWh`      |   `0x3042` |      12354 |           2 | uint32     |   0.01 | L1 forward energy (kWh)                  |
| `E_L1_reverse_kWh`      |   `0x3044` |      12356 |           2 | uint32     |   0.01 | L1 reverse energy (kWh)                  |

### Phase L2 Values

| Key                      | Addr (hex) | Addr (dec) | Size (regs) | Type        | Scale   | Description                              |
|--------------------------|-----------:|-----------:|------------:|------------|--------:|------------------------------------------|
| `U_L2_V`                 |   `0x3048` |      12360 |           1 | int16      |   0.01 | L2 phase‑to‑neutral voltage (V)          |
| `I_L2_A`                 |   `0x3049` |      12361 |           1 | int16      |   0.01 | L2 current (A)                            |
| `P_L2_W`                 |   `0x3086` |      12422 |           2 | int32      |   1.00 | L2 active power (W), signed              |
| `E_L2_forward_kWh`      |   `0x304A` |      12362 |           2 | uint32     |   0.01 | L2 forward energy (kWh)                  |
| `E_L2_reverse_kWh`      |   `0x304C` |      12364 |           2 | uint32     |   0.01 | L2 reverse energy (kWh)                  |

### Phase L3 Values

| Key                      | Addr (hex) | Addr (dec) | Size (regs) | Type        | Scale   | Description                              |
|--------------------------|-----------:|-----------:|------------:|------------|--------:|------------------------------------------|
| `U_L3_V`                 |   `0x3050` |      12368 |           1 | int16      |   0.01 | L3 phase‑to‑neutral voltage (V)          |
| `I_L3_A`                 |   `0x3051` |      12369 |           1 | int16      |   0.01 | L3 current (A)                            |
| `P_L3_W`                 |   `0x308A` |      12426 |           2 | int32      |   1.00 | L3 active power (W), signed              |
| `E_L3_forward_kWh`      |   `0x3052` |      12370 |           2 | uint32     |   0.01 | L3 forward energy (kWh)                  |
| `E_L3_reverse_kWh`      |   `0x3054` |      12372 |           2 | uint32     |   0.01 | L3 reverse energy (kWh)                  |

### Notes on Types and Scaling

- **int16 / int32**: Signed values using two’s complement; negative power indicates export (depending on system wiring).
- **uint16 / uint32**: Unsigned values, always ≥ 0 (used for energy counters).
- **Scale**: Multiply the raw decoded integer by the scale factor to obtain engineering units, exactly as implemented by `read_int16_scaled` / `read_int32_scaled` in `powermeter_via_ip.py`.

---

## Error Handling & Limitations

- If the script cannot connect to the meter, it prints a clear error message and exits.
- If a read fails for key values (e.g. total power), you will see:

  ```text
  Read error: could not read basic registers. Check Modbus settings, device ID, and that no other Modbus master is using the meter.
  ```

- Individual values may be `None` internally if specific Modbus reads fail; where possible, the script prints `NA` for such metrics (e.g. cos φ).

### Known limitations

- The register map is based on **community documentation** (e.g., Home Assistant and Victron community work), not an official public map. It may not cover all registers or future firmware changes.
- Only **read‑only** operations are implemented; the script does not attempt any configuration writes.

---

## Extending the Script

You can easily adapt this code for other purposes:

- **Logging**: Replace or augment the `print(...)` calls with logging to a file, InfluxDB, MQTT, etc.
- **Integrations**: Wrap `read_all(client)` in a small HTTP/REST API or a Home Assistant custom integration.
- **Alarming / automation**: Add thresholds on power, current, or power factor and trigger actions when exceeded.

Typical extension points:

- The `read_all(client)` function: add more registers and keys.
- The `main()` loop: change output format, interval, or push data elsewhere.

---

## File Overview

- `powermeter_via_ip.py` — main script that:
  - Configures connection parameters (`IP_ADDRESS`, `PORT`, `DEVICE_ID`).
  - Implements Modbus helpers and decoding utilities.
  - Reads all relevant registers via `read_all(client)`.
  - Computes per‑phase and total power factors.
  - Prints periodic human‑readable output until interrupted.

- `README.md` — this documentation.

---

## Support & Contributions

This script is a simple example and starting point. If you modify it for new metrics, additional meters, or better integrations, consider documenting the changes for your future self or your team.

If you need help integrating with other tools or extending the functionality, you can ask for guidance with specific goals (e.g., "Log data every minute to CSV" or "Expose readings via a simple REST API").
