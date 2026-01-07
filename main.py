from dsmr_parser import telegram_specifications
from dsmr_parser.clients import SerialReader, SERIAL_SETTINGS_V5
import paho.mqtt.client as mqtt
import simplejson as json
import requests
import urllib3
import threading
import time

# Disable SSL warnings for Envoy self-signed certificate
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# MQTT broker details
broker_address = "192.168.2.10"  # Replace with your MQTT broker's address
port = 1883  # Default MQTT port
# Separate topics for easier debugging
grid_topic = "dsmr/grid"  # For dbus-mqtt-grid
pv_topic = "enphase/pv"   # For dbus-mqtt-pv

# Envoy/IQ Gateway API configuration
envoy_host = "192.168.2.9"  # Replace with your IQ Gateway IP address
envoy_serial = "122041077573"  # Your IQ Gateway serial number (for token retrieval)
pv_poll_interval = 5  # Seconds between PV data fetches

# For IQ Gateway firmware 7.0.x+, you need a token
# Get token via web UI: https://entrez.enphaseenergy.com
# Or programmatically: https://enlighten.enphaseenergy.com/entrez-auth-token?serial_num=YOUR_SERIAL
# Token validity: 1 year for system owners, 12 hours for installers
envoy_token = "eyJraWQiOiI3ZDEwMDA1ZC03ODk5LTRkMGQtYmNiNC0yNDRmOThlZTE1NmIiLCJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiJ9.eyJhdWQiOiIxMjIwNDEwNzc1NzMiLCJpc3MiOiJFbnRyZXoiLCJlbnBoYXNlVXNlciI6Im93bmVyIiwiZXhwIjoxNzk5Mjc0NTgyLCJpYXQiOjE3Njc3Mzg1ODIsImp0aSI6IjE0ZmQ2MmMwLTU3N2ItNGE3YS1iZjdkLTY1OTFkMWQ5MTQyOCIsInVzZXJuYW1lIjoidGhpanNmcmFuc3NlbkBnbWFpbC5jb20ifQ.RGlUTE1bT0Y2KfH93-gBqd93ymBynKxNgOC_DuqbzN6vQ81aPazadzwq7LKdHLqXgfZY5znK6WF6VRbXUSFpHg"  # Required for firmware 7.0.x+

# Shared PV data (updated by background thread)
pv_data = {"power": 0, "energy_forward": 0}
pv_lock = threading.Lock()


def fetch_envoy_production():
    """Fetch current PV production from IQ Gateway local API"""
    try:
        headers = {"Authorization": f"Bearer {envoy_token}"} if envoy_token else {}
        protocol = "https" if envoy_token else "http"
        url = f"{protocol}://{envoy_host}/production.json?details=1"
        
        response = requests.get(url, headers=headers, verify=False, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if "production" in data:
            for item in data["production"]:
                if item.get("type") == "inverters":
                    return {
                        "power": round(item.get("wNow", 0)),
                        "energy_forward": round(item.get("whLifetime", 0) / 1000, 3)
                    }
        return {"power": 0, "energy_forward": 0}
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Envoy data: {e}")
        return None


def pv_polling_thread():
    """Background thread to fetch and publish PV data"""
    global pv_data
    while True:
        result = fetch_envoy_production()
        if result:
            with pv_lock:
                pv_data = result
            # Publish PV data
            pv_message = {"pv": result}
            pv_json = json.dumps(pv_message, use_decimal=True)
            print(f"[{pv_topic}] {pv_json}")
            client.publish(pv_topic, pv_json)
        time.sleep(pv_poll_interval)


print(f"Connecting to MQTT broker at {broker_address}:{port}...")
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(broker_address, port)
client.loop_start()
print("MQTT connected!")

# Start PV polling in background thread
print(f"Starting PV polling thread (every {pv_poll_interval}s)...")
pv_thread = threading.Thread(target=pv_polling_thread, daemon=True)
pv_thread.start()

print(f"Opening serial port /dev/ttyUSB0...")
serial_reader = SerialReader(
    device='/dev/ttyUSB0',
    serial_settings=SERIAL_SETTINGS_V5,
    telegram_specification=telegram_specifications.V5
)
print("Waiting for DSMR telegrams...")

for telegram in serial_reader.read():
    if not client.is_connected():
        print("Connection lost. Reconnecting...")
        client.reconnect()
    
    # Publish grid data immediately (no blocking)
    grid_message = {
        "grid": {
            "power": round(float(telegram.CURRENT_ELECTRICITY_USAGE.value)*1000 - float(telegram.CURRENT_ELECTRICITY_DELIVERY.value)*1000),
            "L1": {
                "power": round(float(telegram.INSTANTANEOUS_ACTIVE_POWER_L1_POSITIVE.value)*1000 - float(telegram.INSTANTANEOUS_ACTIVE_POWER_L1_NEGATIVE.value)*1000, 2),
                "voltage": round(telegram.INSTANTANEOUS_VOLTAGE_L1.value, 2),
                "energy_forward": round(telegram.ELECTRICITY_USED_TARIFF_1.value + telegram.ELECTRICITY_USED_TARIFF_2.value, 2),
                "energy_reverse": round(telegram.ELECTRICITY_DELIVERED_TARIFF_1.value + telegram.ELECTRICITY_DELIVERED_TARIFF_2.value, 2)
            },
            "energy_forward": round(telegram.ELECTRICITY_USED_TARIFF_1.value + telegram.ELECTRICITY_USED_TARIFF_2.value, 2),
            "energy_reverse": round(telegram.ELECTRICITY_DELIVERED_TARIFF_1.value + telegram.ELECTRICITY_DELIVERED_TARIFF_2.value, 2)
        }
    }
    grid_json = json.dumps(grid_message, use_decimal=True)
    print(f"[{grid_topic}] {grid_json}")
    client.publish(grid_topic, grid_json)
    
