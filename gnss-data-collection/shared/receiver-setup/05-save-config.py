import argparse
import serial
from pyubx2 import UBXMessage, SET

parser = argparse.ArgumentParser(description="Save configuration to flash")
parser.add_argument("-p", "--port", default="/dev/cu.usbmodem113301")
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
