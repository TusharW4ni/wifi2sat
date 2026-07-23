import serial
from pyubx2 import UBXReader, UBXMessage  # Fixed import!

PORT = "/dev/cu.usbmodem113301"
BAUD = 115200

def check_config():
    with serial.Serial(PORT, BAUD, timeout=1) as ser:
        # 1. Create a VALGET poll message for the keys we care about
        # layer 0 = RAM (the active configuration)
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
        
        # 2. Send the request (silencing the IDE false-positive)
        ser.write(poll_msg.serialize())  # type: ignore
        
        # 3. Read the incoming stream until we get the VALGET response
        ubr = UBXReader(ser)  # Fixed class name!
        print("Waiting for configuration response...\n")
        
        # 4. Use '_' for the raw data since we only need the parsed data
        for _, parsed_data in ubr:
            # We are looking for the UBX-CFG-VALGET response
            if parsed_data.identity == "CFG-VALGET":
                print("--- Current Receiver Configuration (RAM Layer) ---")
                print(parsed_data)
                break

if __name__ == "__main__":
    check_config()
