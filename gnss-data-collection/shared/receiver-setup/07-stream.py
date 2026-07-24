import serial
from pyubx2 import UBXReader

PORT = "/dev/cu.usbmodem13301"
BAUD = 115200

def stream_receiver():
    print(f"Listening to {PORT} @ {BAUD} baud... (Press Ctrl+C to stop)")
    
    try:
        with serial.Serial(PORT, BAUD, timeout=3) as ser:
            # UBXReader automatically parses UBX, NMEA, and RTCM3 by default
            ubr = UBXReader(ser)
            
            for raw_data, parsed_data in ubr:
                if parsed_data is not None:
                    # This will print the cleanly decoded RTCM3 messages
                    print(parsed_data)
                    
    except serial.SerialException as e:
        print(f"Serial Error: {e}")
    except KeyboardInterrupt:
        print("\nStreaming stopped by user.")

if __name__ == "__main__":
    stream_receiver()
