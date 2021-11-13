#!/usr/bin/env python3

import time
import colorsys
from copy import deepcopy
import sys
import ST7735
try:
    # Transitional fix for breaking change in LTR559
    from ltr559 import LTR559
    ltr559 = LTR559()
except ImportError:
    import ltr559

from bme280 import BME280
from pms5003 import PMS5003, ReadTimeoutError as pmsReadTimeoutError, SerialTimeoutError
from enviroplus import gas
from subprocess import PIPE, Popen
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from fonts.ttf import RobotoMedium as UserFont
import logging

logging.basicConfig(
    format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

# BME280 temperature/pressure/humidity sensor
bme280 = BME280()

# PMS5003 particulate sensor
pms5003 = PMS5003()
time.sleep(1.0)

# Create ST7735 LCD display class
st7735 = ST7735.ST7735(
    port=0,
    cs=1,
    dc=9,
    backlight=12,
    rotation=270,
    spi_speed_hz=10000000
)

# Initialize display
st7735.begin()

WIDTH = st7735.width
HEIGHT = st7735.height

# Set up canvas and font
img = Image.new('RGB', (WIDTH, HEIGHT), color=(0, 0, 0))
draw = ImageDraw.Draw(img)
font_size_small = 10
font_size_large = 20
font = ImageFont.truetype(UserFont, font_size_large)
smallfont = ImageFont.truetype(UserFont, font_size_small)
x_offset = 2
y_offset = 2

message = ""

# The position of the top bar
top_pos = 25

# Create a values dict to store the data
variables = ["temperature",
             "pressure",
             "humidity",
             "light",
             "oxidised",
             "reduced",
             "nh3",
             "pm1",
             "pm25",
             "pm10"]

units = ["C",
         "hPa",
         "%",
         "Lux",
         "kO",
         "kO",
         "kO",
         "ug/m3",
         "ug/m3",
         "ug/m3"]

# Define your own warning limits
# The limits definition follows the order of the variables array
# Example limits explanation for temperature:
# [4,18,28,35] means
# [-273.15 .. 4] -> Dangerously Low
# (4 .. 18]      -> Low
# (18 .. 28]     -> Normal
# (28 .. 35]     -> High
# (35 .. MAX]    -> Dangerously High
# DISCLAIMER: The limits provided here are just examples and come
# with NO WARRANTY. The authors of this example code claim
# NO RESPONSIBILITY if reliance on the following values or this
# code in general leads to ANY DAMAGES or DEATH.
limits = [[4, 18, 28, 35],
          [250, 650, 1013.25, 1015],
          [20, 30, 60, 70],
          [-1, -1, 30000, 100000],
          [-1, -1, 40, 50],
          [-1, -1, 450, 550],
          [-1, -1, 200, 300],
          [-1, -1, 50, 100],
          [-1, -1, 50, 100],
          [-1, -1, 50, 100]]

# RGB palette for values on the combined screen
palette = [(0, 0, 255),           # Dangerously Low
           (0, 255, 255),         # Low
           (0, 255, 0),           # Normal
           (255, 255, 0),         # High
           (255, 0, 0)]           # Dangerously High

return_values = {
            "temp": {
                "unit": "C",
                "desc": "temperature",
                "value": ""
            },
            "pressure": {
                "unit": "hPa",
                "desc": "pressure",
                "value": ""
            },
            "humidity": {
                "unit": "%",
                "desc": "humidity",
                "value": ""
            },
            "light": {
                "unit": "Lux",
                "desc": "light",
                "value": ""
            },
            "oxidised": {
                "unit": "kO",
                "desc": "oxidised",
                "value": ""
            },
            "reduced": {
                "unit": "kO",
                "desc": "reduced",
                "value": ""
            },
            "nh3": {
                "unit": "kO",
                "desc": "nh3",
                "value": ""
            },
            "pm1": {
                "unit": "ug/m3",
                "desc": "pm1",
                "value": ""
            },
            "pm25": {
                "unit": "ug/m3",
                "desc": "pm25",
                "value": ""
            },
            "pm10": {
                "unit": "ug/m3",
                "desc": "pm10",
                "value": ""
            },
        }
values = {}

# Saves the data to be used in the graphs later and prints to the log
def save_data(idx, data):
    variable = variables[idx]
    # Maintain length of list
    values[variable] = values[variable][1:] + [data]
    unit = units[idx]
    message = "{}: {:.1f} {}".format(variable[:4], data, unit)

    if unit == "C":
        return_values["temp"]["value"] = data
    elif unit == "hPa":
        return_values["pressure"]["value"] = data
    elif unit == "%":
        return_values["humidity"]["value"] = data
    elif unit == "Lux":
        return_values["light"]["value"] = data

    if variable == "oxidised":
        return_values["oxidised"]["value"] = data
    if variable == "reduced":
        return_values["reduced"]["value"] = data
    if variable == "nh3":
        return_values["nh3"]["value"] = data
    if variable == "pm1":
        return_values["pm1"]["value"] = data
    if variable == "pm25":
        return_values["pm25"]["value"] = data
    if variable == "pm10":
        return_values["pm10"]["value"] = data



# Get the temperature of the CPU for compensation
def get_cpu_temperature():
    process = Popen(['vcgencmd', 'measure_temp'], stdout=PIPE, universal_newlines=True)
    output, _error = process.communicate()
    return float(output[output.index('=') + 1:output.rindex("'")])


def main():
    # Tuning factor for compensation. Decrease this number to adjust the
    # temperature down, and increase to adjust up
    factor = 2.25

    cpu_temps = [get_cpu_temperature()] * 5

    delay = 0.5  # Debounce the proximity tap
    mode = 10    # The starting mode
    last_page = 0

    for v in variables:
        values[v] = [1] * WIDTH

    # The main loop
    while True:
        proximity = ltr559.get_proximity()

        # If the proximity crosses the threshold, toggle the mode
        if proximity > 1500 and time.time() - last_page > delay:
            mode += 1
            mode %= (len(variables) + 1)
            last_page = time.time()

        # One mode for each variable
        if mode == 0:
            # variable = "temperature"
            unit = "C"
            cpu_temp = get_cpu_temperature()
            # Smooth out with some averaging to decrease jitter
            cpu_temps = cpu_temps[1:] + [cpu_temp]
            avg_cpu_temp = sum(cpu_temps) / float(len(cpu_temps))
            raw_temp = bme280.get_temperature()
            data = raw_temp - ((avg_cpu_temp - raw_temp) / factor)
            display_text(variables[mode], data, unit)

        if mode == 1:
            # variable = "pressure"
            unit = "hPa"
            data = bme280.get_pressure()
            display_text(variables[mode], data, unit)

        if mode == 2:
            # variable = "humidity"
            unit = "%"
            data = bme280.get_humidity()
            display_text(variables[mode], data, unit)

        if mode == 3:
            # variable = "light"
            unit = "Lux"
            if proximity < 10:
                data = ltr559.get_lux()
            else:
                data = 1
            display_text(variables[mode], data, unit)

        if mode == 4:
            # variable = "oxidised"
            unit = "kO"
            data = gas.read_all()
            data = data.oxidising / 1000
            display_text(variables[mode], data, unit)

        if mode == 5:
            # variable = "reduced"
            unit = "kO"
            data = gas.read_all()
            data = data.reducing / 1000
            display_text(variables[mode], data, unit)

        if mode == 6:
            # variable = "nh3"
            unit = "kO"
            data = gas.read_all()
            data = data.nh3 / 1000
            display_text(variables[mode], data, unit)

        if mode == 7:
            # variable = "pm1"
            unit = "ug/m3"
            try:
                data = pms5003.read()
            except pmsReadTimeoutError:
                logging.warning("Failed to read PMS5003")
            else:
                data = float(data.pm_ug_per_m3(1.0))
                display_text(variables[mode], data, unit)

        if mode == 8:
            # variable = "pm25"
            unit = "ug/m3"
            try:
                data = pms5003.read()
            except pmsReadTimeoutError:
                logging.warning("Failed to read PMS5003")
            else:
                data = float(data.pm_ug_per_m3(2.5))
                display_text(variables[mode], data, unit)

        if mode == 9:
            # variable = "pm10"
            unit = "ug/m3"
            try:
                data = pms5003.read()
            except pmsReadTimeoutError:
                logging.warning("Failed to read PMS5003")
            else:
                data = float(data.pm_ug_per_m3(10))
                display_text(variables[mode], data, unit)
        if mode == 10:
            # Everything on one screen
            cpu_temp = get_cpu_temperature()
            # Smooth out with some averaging to decrease jitter
            cpu_temps = cpu_temps[1:] + [cpu_temp]
            avg_cpu_temp = sum(cpu_temps) / float(len(cpu_temps))
            raw_temp = bme280.get_temperature()
            raw_data = raw_temp - ((avg_cpu_temp - raw_temp) / factor)
            save_data(0, raw_data)
            raw_data = bme280.get_pressure()
            save_data(1, raw_data)
            raw_data = bme280.get_humidity()
            save_data(2, raw_data)
            if proximity < 10:
                raw_data = ltr559.get_lux()
            else:
                raw_data = 1
            save_data(3, raw_data)
            gas_data = gas.read_all()
            save_data(4, gas_data.oxidising / 1000)
            save_data(5, gas_data.reducing / 1000)
            save_data(6, gas_data.nh3 / 1000)
            pms_data = None
            try:
                pms_data = pms5003.read()
            except (SerialTimeoutError, pmsReadTimeoutError):
                logging.warning("Failed to read PMS5003")
            else:
                save_data(7, float(pms_data.pm_ug_per_m3(1.0)))
                save_data(8, float(pms_data.pm_ug_per_m3(2.5)))
                save_data(9, float(pms_data.pm_ug_per_m3(10)))

        print(return_values)

        time.sleep(1)


if __name__ == "__main__":
    main()

