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
