from dsmr_parser import telegram_specifications
from dsmr_parser.clients import SerialReader, SERIAL_SETTINGS_V5
import paho.mqtt.client as mqtt
import simplejson as json
import requests
import urllib3

# Disable SSL warnings for Envoy self-signed certificate
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# MQTT broker details
broker_address = "192.168.2.40"  # Replace with your MQTT broker's address
port = 1883  # Default MQTT port
grid_topic = "enphase/envoy-s/meters"  # MQTT topic for grid data
pv_topic = "pv/SENSOR"  # MQTT topic for PV data (dbus-mqtt-pv compatible)

# Envoy/IQ Gateway API configuration
envoy_host = "192.168.2.9"  # Replace with your IQ Gateway IP address
envoy_serial = "122041077573"  # Your IQ Gateway serial number (for token retrieval)

# For IQ Gateway firmware 7.0.x+, you need a token
# Get token via web UI: https://entrez.enphaseenergy.com
# Or programmatically: https://enlighten.enphaseenergy.com/entrez-auth-token?serial_num=YOUR_SERIAL
# Token validity: 1 year for system owners, 12 hours for installers
envoy_token = "eyJraWQiOiI3ZDEwMDA1ZC03ODk5LTRkMGQtYmNiNC0yNDRmOThlZTE1NmIiLCJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiJ9.eyJhdWQiOiIxMjIwNDEwNzc1NzMiLCJpc3MiOiJFbnRyZXoiLCJlbnBoYXNlVXNlciI6Im93bmVyIiwiZXhwIjoxNzk5Mjc0NTgyLCJpYXQiOjE3Njc3Mzg1ODIsImp0aSI6IjE0ZmQ2MmMwLTU3N2ItNGE3YS1iZjdkLTY1OTFkMWQ5MTQyOCIsInVzZXJuYW1lIjoidGhpanNmcmFuc3NlbkBnbWFpbC5jb20ifQ.RGlUTE1bT0Y2KfH93-gBqd93ymBynKxNgOC_DuqbzN6vQ81aPazadzwq7LKdHLqXgfZY5znK6WF6VRbXUSFpHg"  # Required for firmware 7.0.x+


def get_envoy_production():
    """
    Fetch current PV production from IQ Gateway local API
    See: https://enphase.com/download/iq-gateway-local-apis-or-ui-access-using-token
    """
    try:
        headers = {"Authorization": f"Bearer {envoy_token}"} if envoy_token else {}
        
        # Use HTTPS for firmware 7.0.x+ with token, HTTP for older firmware
        protocol = "https" if envoy_token else "http"
        url = f"{protocol}://{envoy_host}/production.json?details=1"
        
        response = requests.get(url, headers=headers, verify=False, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        result = {"power": 0, "energy_forward": 0}
        
        # Parse production data from inverters
        if "production" in data:
            for item in data["production"]:
                if item.get("type") == "inverters":
                    result["power"] = round(item.get("wNow", 0))
                    result["energy_forward"] = round(item.get("whLifetime", 0) / 1000, 3)  # Wh to kWh
                    break
        
        return result
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Envoy production data: {e}")
        return None


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(broker_address, port)
client.loop_start()


serial_reader = SerialReader(
    device='/dev/ttyUSB0',
    serial_settings=SERIAL_SETTINGS_V5,
    telegram_specification=telegram_specifications.V5
)

for telegram in serial_reader.read():
    # Get grid data from smart meter
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
    
    # Get PV production from Envoy
    pv_data = get_envoy_production()
    
    if not client.is_connected():
        print("Connection lost. Reconnecting...")
        client.reconnect()
    
    # Publish grid data
    grid_json = json.dumps(grid_message, use_decimal=True)
    print(f"Grid: {grid_json}")
    client.publish(grid_topic, grid_json)
    
    # Publish PV data in dbus-mqtt-pv compatible format
    if pv_data:
        pv_message = {
            "pv": {
                "power": pv_data["power"],
                "energy_forward": pv_data["energy_forward"]
            }
        }
        pv_json = json.dumps(pv_message, use_decimal=True)
        print(f"PV: {pv_json}")
        client.publish(pv_topic, pv_json)
    
