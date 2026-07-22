"""
[1] https://github.com/semuconsulting/pyubx2/blob/master/src/pyubx2/ubxtypes_core.py
[2] https://github.com/semuconsulting/pyubx2/blob/master/src/pyubx2/ubxtypes_set.py
[3] https://content.u-blox.com/sites/default/files/documents/u-blox-F9-HPG-L1L5-1.40_InterfaceDescription_UBX-23006991.pdf
[4] https://github.com/semuconsulting/pyubx2/blob/master/src/pyubx2/ubxmessage.py
"""

import argparse
import serial
from pyubx2 import UBXMessage

parser = argparse.ArgumentParser(description="Reset u-blox EVK-F9P receiver (Cold Start)")
parser.add_argument("-p", "--port", default="/dev/cu.usbmodem113301", help="Serial port")
parser.add_argument("-b", "--baud", type=int, default=115200, help="Baud rate (default: 115200)")
parser.add_argument("-mode", "--resetMode", type=int, default=0x01, 
                    help="Reset Mode: 0x01=Hardware, 0x02=Software (default: 0x01)")
args = parser.parse_args()

if __name__ == "__main__":
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)

        reset_msg = UBXMessage( 
            ubxClass="CFG", # [4]
            ubxID="CFG-RST", # [4]
            msgmode=1, # [4]
            # [3] navBbrMask= 
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
            resetMode=0x01 # [3]
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
