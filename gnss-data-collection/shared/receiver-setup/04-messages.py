import argparse
import serial
from pyubx2 import UBXMessage, SET

parser = argparse.ArgumentParser(description="Configure message outputs (RAWX + SFRBX + MSM7 + NAV-SAT, NMEA off)")
parser.add_argument("-p", "--port", default="/dev/cu.usbmodem11301")
parser.add_argument("-b", "--baud", type=int, default=115200)
args = parser.parse_args()

if __name__ == "__main__":
    ser = serial.Serial(args.port, args.baud, timeout=1)

    # --- Disable NMEA ---
    NMEA_MSGS = [(0xF0, 0x00), (0xF0, 0x04), (0xF0, 0x03), (0xF0, 0x02)]  # GGA RMC GSV GSA
    for cls_id, msg_id in NMEA_MSGS:
        ser.write(UBXMessage("CFG", "CFG-MSG", msgmode=SET,
                             msgClass=cls_id, msgID=msg_id, rateUART1=0, rateUSB=0).serialize())

    # --- Enable UBX-RXM-RAWX (continuous carrier phase: cpMes, locktime, trkStat) ---
    # This is now the PRIMARY carrier-phase observable. rateUSB=1 -> every epoch (10 Hz).
    ser.write(UBXMessage("CFG", "CFG-MSG", msgmode=SET,
                         msgClass=0x02, msgID=0x15, rateUSB=1).serialize())   # RXM-RAWX

    # --- Enable UBX-RXM-SFRBX (broadcast nav/ephemeris) ---
    # Lets us compute precise satellite positions -> precise LOS vectors, instead
    # of relying on NAV-SAT az/el which is only 1-degree resolution. Low volume.
    ser.write(UBXMessage("CFG", "CFG-MSG", msgmode=SET,
                         msgClass=0x02, msgID=0x13, rateUSB=1).serialize())   # RXM-SFRBX

    # --- Keep UBX-NAV-SAT (quick az/el; coarse but convenient) ---
    ser.write(UBXMessage("CFG", "CFG-MSG", msgmode=SET,
                         msgClass=0x01, msgID=0x35, rateUSB=10).serialize())  # NAV-SAT @1Hz

    # --- Keep RTCM 1077 (GPS MSM7) and 1127 (BeiDou MSM7) ---
    # Retained so we can cross-validate / calibrate the MSM reconstruction against
    # RAWX cpMes (ground truth), and to recover the MSM-only data already collected.
    ser.write(UBXMessage("CFG", "CFG-MSG", msgmode=SET,
                         msgClass=0xF5, msgID=0x4D, rateUSB=1).serialize())   # 1077 GPS MSM7
    ser.write(UBXMessage("CFG", "CFG-MSG", msgmode=SET,
                         msgClass=0xF5, msgID=0x7F, rateUSB=1).serialize())   # 1127 BDS MSM7

    print("--- Messages Configured ---")
    print("RAWX (10Hz) + SFRBX + NAV-SAT (1Hz) + RTCM 1077/1127 enabled. NMEA disabled.")
    print("Note: USB CDC is not baud-limited, so 10Hz RAWX+MSM (~12 KB/s) is fine.")
    print("      On UART1 @115200 this would overflow -- raise to >=230400 if you move off USB.")

    ser.close()
