# GNSS Receiver Setup Scripts

All setup scripts live in `setup-receiver/`. Run them via the orchestrator or individually with `uv run`.

---

## 0. Install Dependencies

```toml
# pyproject.toml — install with: uv sync
[project]
name = "gnss-data-collection"
requires-python = ">=3.12"
dependencies = [
    "pyserial>=3.5",
    "pyubx2>=1.2.60",
    "numpy>=2.4.4",
    "scipy>=1.17.1",
    "scikit-learn>=1.8.0",
    "xgboost>=3.2.0",
    "matplotlib>=3.10.9",
    "seaborn>=0.13.2",
    "ipykernel>=7.2.0",
]
```

```bash
uv sync
```

---

## 1. Orchestrator — `setup-receiver/setup.zsh`

Runs steps 1–6 sequentially with timed waits between them.

```zsh
#!/bin/zsh

# --- COLOR DEFINITIONS ---
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# --- HELPER FUNCTION ---
print_step() {
    echo -e "\n${BLUE}============================================================${NC}"
    echo -e "${GREEN}▶ Running: ${YELLOW}$1${NC}"
    echo -e "${BLUE}============================================================${NC}"
}

echo -e "${GREEN}Starting U-blox Configuration Sequence...${NC}"

# STEP 1: Reset
print_step "uv run 01-reset.py"
uv run 01-reset.py
# 10-second in-place countdown
for i in {10..1}; do
    printf "\r${YELLOW}Waiting %d seconds for receiver to cold boot...${NC}" "$i"
    sleep 1
done
echo ""

# STEP 2: Sample Rate
print_step "uv run 02-sample-rate.py"
uv run 02-sample-rate.py
sleep 1

# STEP 3: Port Config
print_step "uv run 03-port-config.py"
uv run 03-port-config.py
sleep 1

# STEP 4: Messages
print_step "uv run 04-messages.py"
uv run 04-messages.py
sleep 1

# STEP 5: Save Config
print_step "uv run 05-save-config.py"
uv run 05-save-config.py
# 5-second in-place countdown
for i in {5..1}; do
    printf "\r${YELLOW}Waiting %d seconds for flash write to complete...${NC}" "$i"
    sleep 1
done
echo ""

# STEP 6: Check Config
print_step "uv run 06-check.py"
uv run 06-check.py
sleep 2
```

---

## 2. Step 1 — Cold Start Reset — `setup-receiver/01-reset.py`

Clears all battery-backed RAM (ephemeris, almanac, position, clock, etc.) and issues a hardware reset.

```python
import argparse
import serial
from pyubx2 import UBXMessage

parser = argparse.ArgumentParser(description="Reset u-blox EVK-F9P receiver (Cold Start)")
parser.add_argument("-p", "--port", default="/dev/cu.usbmodem11301", help="Serial port")
parser.add_argument("-b", "--baud", type=int, default=115200, help="Baud rate (default: 115200)")
parser.add_argument("-mode", "--resetMode", type=int, default=0x01,
                    help="Reset Mode: 0x01=Hardware, 0x02=Software (default: 0x01)")
args = parser.parse_args()

if __name__ == "__main__":
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)

        reset_msg = UBXMessage(
            ubxClass="CFG",
            ubxID="CFG-RST",
            msgmode=1,
            eph=1,
            alm=1,
            health=1,
            klob=1,
            pos=1,
            clkd=1,
            osc=1,
            utc=1,
            rtc=1,
            aop=1,
            resetMode=0x01
        )

        ser.write(reset_msg.serialize())

        print(f"--- Reset Command Sent ---")
        print(f"Port: {args.port} @ {args.baud}")
        print(f"Action: Cold Start (All BBR data cleared)")
        print(f"Mode: {hex(args.resetMode)}")

        ser.close()
    except serial.SerialException as e:
        print(f"Serial Error: Could not open port {args.port}. {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
```

> After this step the orchestrator waits **10 seconds** for the receiver to complete its cold boot.

---

## 3. Step 2 — Measurement Rate — `setup-receiver/02-sample-rate.py`

Sets measurement rate to 100 ms (10 Hz), navigation rate to 1 cycle, time reference to GPS.

```python
import argparse
import serial
from pyubx2 import UBXMessage, SET

parser = argparse.ArgumentParser(description="Configure u-blox Navigation/Measurement Rate")
parser.add_argument("-p", "--port", default="/dev/cu.usbmodem11301", help="Serial port")
parser.add_argument("-b", "--baud", type=int, default=115200, help="Baud rate (default: 115200)")
parser.add_argument("-m", "--measRate", type=int, default=100,
                    help="Measurement rate in ms (e.g., 100 for 10Hz)")
parser.add_argument("-n", "--navRate", type=int, default=1,
                    help="Navigation rate in cycles (usually 1)")
parser.add_argument("-t", "--timeRef", type=int, choices=[0, 1, 2, 3, 4, 5], default=1,
                    help="Time alignment (0:UTC, 1:GPS)")

args = parser.parse_args()

if __name__ == "__main__":
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)

        rate_msg = UBXMessage(
            "CFG",
            "CFG-RATE",
            msgmode=SET,
            measRate=args.measRate,
            navRate=args.navRate,
            timeRef=args.timeRef
        )

        ser.write(rate_msg.serialize())

        print(f"--- Configuration Sent ---")
        print(f"Port: {args.port} @ {args.baud}")
        print(f"Rate: {args.measRate}ms ({1000/args.measRate}Hz)")

        ser.close()
    except serial.SerialException as e:
        print(f"Serial Error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
```

---

## 4. Step 3 — Port Protocol Config — `setup-receiver/03-port-config.py`

Configures UART1/USB port to accept and output only UBX + RTCM3 (disables NMEA).

```python
import argparse
import serial
from pyubx2 import UBXMessage, SET

parser = argparse.ArgumentParser(description="Configure port protocols (disable NMEA)")
parser.add_argument("-p", "--port", default="/dev/cu.usbmodem11301")
parser.add_argument("-b", "--baud", type=int, default=115200)

args = parser.parse_args()

if __name__ == "__main__":
    ser = serial.Serial(args.port, args.baud, timeout=1)

    msg = UBXMessage(
        "CFG",
        "CFG-PRT",
        msgmode=SET,
        portID=1,
        baudRate=args.baud,
        inProtoMask=0x0005,   # UBX + RTCM
        outProtoMask=0x0005   # UBX + RTCM
    )

    ser.write(msg.serialize())

    print("--- Port Configured ---")
    print("Protocols: UBX + RTCM (NMEA disabled)")

    ser.close()
```

---

## 5. Step 4 — Message Output Config — `setup-receiver/04-messages.py`

Disables NMEA sentences (GGA, RMC, GSV, GSA), enables UBX-NAV-SAT at 10-cycle rate, enables RTCM 1077 (GPS MSM7) and RTCM 1127 (BeiDou MSM7) at 1-cycle rate. RAWX is present but commented out.

```python
import argparse
import serial
from pyubx2 import UBXMessage, SET

parser = argparse.ArgumentParser(description="Configure message outputs (RAWX, NAV-SAT + disable NMEA)")
parser.add_argument("-p", "--port", default="/dev/cu.usbmodem11301")
parser.add_argument("-b", "--baud", type=int, default=115200)

args = parser.parse_args()

if __name__ == "__main__":
    ser = serial.Serial(args.port, args.baud, timeout=1)

    # --- Disable NMEA ---
    NMEA_MSGS = [
        (0xF0, 0x00),  # GGA
        (0xF0, 0x04),  # RMC
        (0xF0, 0x03),  # GSV
        (0xF0, 0x02),  # GSA
    ]

    for cls_id, msg_id in NMEA_MSGS:
        msg = UBXMessage(
            "CFG",
            "CFG-MSG",
            msgmode=SET,
            msgClass=cls_id,
            msgID=msg_id,
            rateUART1=0,
            rateUSB=0
        )
        ser.write(msg.serialize())

    # --- Enable RAWX (disabled) ---
    rawx_msg = UBXMessage(
        "CFG",
        "CFG-MSG",
        msgmode=SET,
        msgClass=0x02,   # RXM
        msgID=0x15,      # RAWX
        rateUSB=1
    )
    # ser.write(rawx_msg.serialize())

    # --- Enable UBX-NAV-SAT (Elevation Data) ---
    nav_sat_msg = UBXMessage(
        "CFG",
        "CFG-MSG",
        msgmode=SET,
        msgClass=0x01,   # NAV
        msgID=0x35,      # SAT
        rateUSB=10
    )
    ser.write(nav_sat_msg.serialize())

    # --- Enable RTCM 1077 (GPS MSM7) ---
    msg_1077 = UBXMessage(
        "CFG",
        "CFG-MSG",
        msgmode=SET,
        msgClass=0xF5,
        msgID=0x4D,
        rateUSB=1
    )
    ser.write(msg_1077.serialize())

    # --- Enable RTCM 1127 (BeiDou MSM7) ---
    msg_1127 = UBXMessage(
        "CFG",
        "CFG-MSG",
        msgmode=SET,
        msgClass=0xF5,
        msgID=0x7F,
        rateUSB=1
    )
    ser.write(msg_1127.serialize())

    print("--- Messages Configured ---")
    print("RAWX, NAV-SAT, RTCM enabled. NMEA disabled.")

    ser.close()
```

---

## 6. Step 5 — Save Configuration to Flash — `setup-receiver/05-save-config.py`

Persists the active RAM configuration to flash so it survives power cycles.

```python
import argparse
import serial
from pyubx2 import UBXMessage, SET

parser = argparse.ArgumentParser(description="Save configuration to flash")
parser.add_argument("-p", "--port", default="/dev/cu.usbmodem11301")
parser.add_argument("-b", "--baud", type=int, default=115200)

args = parser.parse_args()

if __name__ == "__main__":
    ser = serial.Serial(args.port, args.baud, timeout=1)

    save_msg = UBXMessage(
        "CFG",
        "CFG-CFG",
        msgmode=SET,
        saveMask=b'\xff\xff\x00\x00',
        loadMask=b'\x00\x00\x00\x00',
        clearMask=b'\x00\x00\x00\x00',
        devMask=b'\x01'
    )

    ser.write(save_msg.serialize())

    print("--- Configuration Saved to Flash ---")

    ser.close()
```

> After this step the orchestrator waits **5 seconds** for the flash write to complete.

---

## 7. Step 6 — Verify Configuration — `setup-receiver/06-check.py`

Polls the RAM layer via `CFG-VALGET` and prints the active values for all configured keys.

```python
import serial
from pyubx2 import UBXReader, UBXMessage

PORT = "/dev/cu.usbmodem11301"
BAUD = 115200

def check_config():
    with serial.Serial(PORT, BAUD, timeout=1) as ser:
        poll_msg = UBXMessage.config_poll(
            layer=0,
            position=0,
            keys=[
                "CFG_RATE_MEAS",
                "CFG_UART1_BAUDRATE",
                "CFG_USBOUTPROT_NMEA",
                "CFG_MSGOUT_UBX_NAV_SAT_USB",
                "CFG_MSGOUT_UBX_RXM_RAWX_USB",
                "CFG_MSGOUT_RTCM_3X_TYPE1077_USB",
                "CFG_MSGOUT_RTCM_3X_TYPE1127_USB"
            ]
        )

        ser.write(poll_msg.serialize())  # type: ignore

        ubr = UBXReader(ser)
        print("Waiting for configuration response...\n")

        for _, parsed_data in ubr:
            if parsed_data.identity == "CFG-VALGET":
                print("--- Current Receiver Configuration (RAM Layer) ---")
                print(parsed_data)
                break

if __name__ == "__main__":
    check_config()
```

---

## 8. Utility — Live Message Stream — `setup-receiver/07-stream.py`

Real-time monitor; prints all decoded UBX / NMEA / RTCM3 messages from the receiver. Run independently after setup to confirm data flow.

```python
import serial
from pyubx2 import UBXReader

PORT = "/dev/cu.usbmodem11301"
BAUD = 115200

def stream_receiver():
    print(f"Listening to {PORT} @ {BAUD} baud... (Press Ctrl+C to stop)")

    try:
        with serial.Serial(PORT, BAUD, timeout=3) as ser:
            ubr = UBXReader(ser)

            for raw_data, parsed_data in ubr:
                if parsed_data is not None:
                    print(parsed_data)

    except serial.SerialException as e:
        print(f"Serial Error: {e}")
    except KeyboardInterrupt:
        print("\nStreaming stopped by user.")

if __name__ == "__main__":
    stream_receiver()
```
