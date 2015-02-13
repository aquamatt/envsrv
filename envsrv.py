from __future__ import division
import json
import serial
import time
import threading
import sys

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

from settings import *

librato = librato.connect(LIBRATO_USER, LIBRATO_TOKEN)

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
    logger.info(v)
    return v


class PowerAccumulator(threading.Thread):
    def __init__(self, reporting_interval=60):
        super(PowerAccumulator, self).__init__()
        self.daemon = True
        self.dt_millis = 0
        self.intervals = 0
        self.reporting_interval = reporting_interval
        self.publish_queue = Queue()

    def add(self, dt):
        self.dt_millis += dt
        self.intervals += 1
        self.check()

    def check(self):
        if self.dt_millis/1000 >= self.reporting_interval:
            self.publish_queue.put(1000*(3600*self.intervals) / self.dt_millis)
            self.dt_millis = 0
            self.intervals = 0

    def run(self):
        while True:
            p = self.publish_queue.get()
            content = make_gecko_meter(p, 0, 4500)
            requests.post(GECKO_URL_ROOT + GECKO_POWER_KEY, content)

power_accumulator = PowerAccumulator(reporting_interval=5)
power_accumulator.start()

OUTFILE = "/mnt/energy_ticker"
COMPUTED_TIME = 0

def log(computed, delta):
    with open("/mnt/energy_ticker", "at") as output:
        output.write("{},{},{}\n".format(time.time(), computed, delta))
    
def process(v):
    global COMPUTED_TIME
    key, value = v.split("=")
    if key == "I":
        if COMPUTED_TIME == 0:
            COMPUTED_TIME = time.time()
        else:
	    COMPUTED_TIME += int(value)/1000.0
        log(COMPUTED_TIME, value)
        power_accumulator.add(int(value))
    

DEVICE = "/dev/ttyAMA0"
ser = serial.Serial(DEVICE, 38400)
ser.open()
v=""
while 1:
    ch = ser.read()
    if ch == "\n":
        process(v)
        v=""
    elif ch == "\r":
        pass
    else:
        v += ch
ser.close()
