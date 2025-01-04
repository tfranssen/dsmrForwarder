from dsmr_parser import telegram_specifications
from dsmr_parser.clients import SerialReader, SERIAL_SETTINGS_V5
import paho.mqtt.client as mqtt
import simplejson as json


# MQTT broker details
broker_address = "192.168.2.40"  # Replace with your MQTT broker's address
port = 1883  # Default MQTT port
topic = "enphase/envoy-s/meters"  # Replace with the MQTT topic you want to publish to

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
client.connect(broker_address, port)

client.loop_start();


serial_reader = SerialReader(
    device='/dev/ttyUSB0',
    serial_settings=SERIAL_SETTINGS_V5,
    telegram_specification=telegram_specifications.V5
)

for telegram in serial_reader.read():
    #print(str(telegram.CURRENT_ELECTRICITY_USAGE.value))  # see 'Telegram object' docs below
    mqtt_message = {
        "grid": {
        "power": round(float(telegram.CURRENT_ELECTRICITY_USAGE.value)*1000 - float(telegram.CURRENT_ELECTRICITY_DELIVERY.value)*1000),
        "L1": {
            "power": round(float(telegram.INSTANTANEOUS_ACTIVE_POWER_L1_POSITIVE.value)*1000 - float(telegram.INSTANTANEOUS_ACTIVE_POWER_L1_NEGATIVE.value)*1000,2),
            "voltage": round(telegram.INSTANTANEOUS_VOLTAGE_L1.value,2),
            "energy_forward": round(telegram.ELECTRICITY_USED_TARIFF_1.value + telegram.ELECTRICITY_USED_TARIFF_2.value,2),
            "energy_reverse": round(telegram.ELECTRICITY_DELIVERED_TARIFF_1.value + telegram.ELECTRICITY_DELIVERED_TARIFF_2.value,2)
        },
        
        "energy_forward": round(telegram.ELECTRICITY_USED_TARIFF_1.value + telegram.ELECTRICITY_USED_TARIFF_2.value,2),
        "energy_reverse": round(telegram.ELECTRICITY_DELIVERED_TARIFF_1.value + telegram.ELECTRICITY_DELIVERED_TARIFF_2.value,2)
        }
    }
    #print(mqtt_message)
    json_string = json.dumps(mqtt_message, use_decimal=True)
    print(json_string)
    if not client.is_connected():
        print("Connection lost. Reconnecting...")
        client.reconnect()
    client.publish(topic, json_string)
    
