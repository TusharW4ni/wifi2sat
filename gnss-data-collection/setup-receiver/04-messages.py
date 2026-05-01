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

    # --- Enable RAWX ---
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
        # msgID=0x57,
        msgID=0x7F,
        rateUSB=1
    )
    ser.write(msg_1127.serialize())

    print("--- Messages Configured ---")
    print("RAWX, NAV-SAT, RTCM enabled. NMEA disabled.")

    ser.close()