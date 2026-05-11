import asyncio
import json
import logging
from bleak import BleakClient, BleakScanner
from aiomqtt import Client as MqttClient

# --- CONFIGURATION ---
# REPLACE THESE VALUES
DEVICE_MAC = "XX:XX:XX:XX:XX:XX"  # <--- Your Anker MAC Address
MQTT_BROKER = "vesta.local"     # <--- Your MQTT Broker IP
MQTT_PORT = 1883
MQTT_USER = "your_mqtt_username"
MQTT_PASS = "your_mqtt_password"
TOPIC_PREFIX = "anker/767"
# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# --- HELPERS ---
def get_int16(frame, offset):
    """Read 2 bytes as Little Endian"""
    try:
        return int.from_bytes(frame[offset:offset+2], byteorder='little')
    except IndexError:
        return 0
def format_time(minutes):
    """Convert minutes to human readable string (1d 2h 30m)"""
    if minutes == 0 or minutes > 60000: return "Calculating..."
    days = minutes // 1440
    hours = (minutes % 1440) // 60
    mins = minutes % 60
    if days > 0: return f"{days}d {hours}h {mins}m"
    elif hours > 0: return f"{hours}h {mins}m"
    else: return f"{mins}m"
# --- PARSING LOGIC ---
def parse_frame(frame: bytearray):
    try:
        # Basic bounds check
        if len(frame) < 76: return {}
        data = {
            # Battery Levels
            "battery_level": frame[70],
            "expansion_battery_level": frame[71] if len(frame) > 71 else 0,
            
            # Temperatures
            "battery_temp": frame[66],
            "expansion_temp": frame[67] if len(frame) > 67 else 0,
            # Power IO
            "ac_output_w": get_int16(frame, 21),
            "solar_input_w": get_int16(frame, 37),
            "total_input_w": get_int16(frame, 39), # Grid + Solar
            "total_output_w": get_int16(frame, 41),
            
            # Time Calculation
            "minutes_remaining": get_int16(frame, 76),
        }
        
        data["time_remaining_str"] = format_time(data["minutes_remaining"])
        return data
    except IndexError:
        return {}
# --- MQTT HANDLERS ---
async def main():
    while True:
        try:
            logging.info(f"Scanning for {DEVICE_MAC}...")
            device = await BleakScanner.find_device_by_address(DEVICE_MAC, timeout=20)
            if not device:
                logging.warning("Device not found, retrying in 10s...")
                await asyncio.sleep(10)
                continue
            
            async with MqttClient(hostname=MQTT_BROKER, port=MQTT_PORT, username=MQTT_USER, password=MQTT_PASS) as mqtt:
                async with BleakClient(device) as client:
                    logging.info(f"Connected to Anker 767!")
                    
                    async def notification_handler(_sender, data):
                        parsed = parse_frame(data)
                        if parsed:
                            await mqtt.publish(f"{TOPIC_PREFIX}/state", json.dumps(parsed))
                            logging.info(f"Published: Bat {parsed['battery_level']}% | In {parsed['total_input_w']}W")
                    # Auto-detect notify characteristic
                    notify_uuid = None
                    for s in client.services:
                        for c in s.characteristics:
                            if "notify" in c.properties:
                                notify_uuid = c.uuid
                                break
                        if notify_uuid: break
                    if notify_uuid:
                        await client.start_notify(notify_uuid, notification_handler)
                        while client.is_connected:
                            await asyncio.sleep(1)
                    else:
                        logging.error("No notify characteristic found.")
        except Exception as e:
            logging.error(f"Connection lost: {e}. Restarting...")
            await asyncio.sleep(5)
if __name__ == "__main__":
    asyncio.run(main())