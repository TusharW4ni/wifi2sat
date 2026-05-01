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
