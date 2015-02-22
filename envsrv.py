from __future__ import division
from datetime import datetime
import json
import logging
import serial
import time
import threading

import librato
import requests

from Queue import Queue

# Librato setup
LIBRATO_USER = 'PUT IN SETTINGS'
LIBRATO_TOKEN = 'PUT IN SETTINGS'

# Geckoboard setup
GECKO_URL_ROOT = "https://push.geckoboard.com/v1/send/"
GECKO_API_KEY = "PUT IN SETTINGS"
GECKO_POWER_KEY = "PUT IN SETTINGS"
GECKO_CHART_KEY = "PUT IN SETTINGS"

from settings import *

librato = librato.connect(LIBRATO_USER, LIBRATO_TOKEN)


def init_logging(filename='/mnt/envsrv.log', level=logging.DEBUG):
    logging.basicConfig(
        filename=filename,
        level=level,
        format='%(levelname)s: %(asctime)s %(message)s',
        datefmt='%d/%m/%Y %H:%M:%S',
        filemode="a")


def make_gecko_meter(value, minimum, maximum):
    d = dict(
        item=value,
        min=dict(value=minimum),
        max=dict(value=maximum),
        )
    return json.dumps(dict(api_key=GECKO_API_KEY, data=d))


def make_gecko_number_secondary_stat(value, text=''):
    d = dict(
        item=[
            dict(
                value=value,
                text=text)
            ]
        )

    v = json.dumps(dict(api_key=GECKO_API_KEY, data=d))
    return v


def make_gecko_line_chart(data, title=''):
    d = dict(
        x_axis=dict(type="datetime"),
        series=[dict(name=title, data=data)],
        )
    v = json.dumps(dict(api_key=GECKO_API_KEY, data=d))
    return v


class PowerAccumulator(threading.Thread):
    def __init__(self, reporting_interval=60, history_points=100):
        super(PowerAccumulator, self).__init__()
        self.daemon = True
        self.dt_millis = 0
        self.intervals = 0
        self.reporting_interval = reporting_interval
        self.publish_queue = Queue()
        self.history_points = history_points
        self.history = []

    def add(self, dt):
        self.dt_millis += dt
        self.intervals += 1
        self.check()

    def check(self):
        if self.dt_millis/1000 >= self.reporting_interval:
            power = (3600000*self.intervals) / self.dt_millis
            self.dt_millis = 0
            self.intervals = 0

            self.history.append([datetime.now().isoformat().split('.')[0],
                                 power])
            self.history = self.history[-self.history_points:]

            self.publish_queue.put(power)

    def run(self):
        while True:
            power = self.publish_queue.get()
            logging.info("Publishing power dP={}".format(power))

            # Geckoboard
            meter_content = make_gecko_meter(power, 0, 4500)
            try:
                requests.post(GECKO_URL_ROOT + GECKO_POWER_KEY, meter_content)
            except Exception:
                logging.exception("Error posting to Gecko meter")
            chart_content = make_gecko_line_chart(
                data=self.history,
                title="Power consumption")
            try:
                requests.post(GECKO_URL_ROOT + GECKO_CHART_KEY, chart_content)
            except Exception:
                logging.exception("Error posting to Gecko chart")

            # Librato
            try:
                with librato.new_queue() as queue:
                    queue.add("home_electricity_watts",
                              power,
                              source="home",
                              description="Domestic electricity consumption")
                    queue.submit()
            except Exception, ex:
                logger.exception("Error posting to librato")


power_accumulator = PowerAccumulator(reporting_interval=5, history_points=300)
power_accumulator.start()


OUTFILE = "/mnt/energy_ticker.csv"


def log(delta):
    with open(OUTFILE, "at") as output:
        output.write("{},{},{}\n".format(datetime.now().isoformat(),
                                         time.time(),
                                         delta))


def process(v):
    try:
        key, value = v.split("=")
        if key == "I":
            log(value)
            power_accumulator.add(int(value))
    except ValueError:
        # likely that we couldn't unpack two values in the split because
        # programme started mid way between transmission from the uC
        pass


if __name__ == '__main__':
    init_logging(level=logging.INFO)
    DEVICE = "/dev/ttyAMA0"
    ser = serial.Serial(DEVICE, 38400)
    ser.open()
    v = ""
    while 1:
        ch = ser.read()
        if ch == "\n":
            process(v)
            v = ""
        elif ch == "\r":
            pass
        else:
            v += ch
    ser.close()
