import csv
import os
import random
from typing import Dict, List, Set, Tuple

import joblib
import numpy as np
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
import threading
import time
from statsd import StatsClient

lock = threading.Lock()


class SimWatcher(PatternMatchingEventHandler):
    """
    Watchdog event handler for each simulation

    """
    patterns = ['cu-up-cell-1.txt', 'cu-cp-cell-*.txt', "du-cell-*.txt"]
    kpm_map: Dict[Tuple[int, int], List] = {}
    consumed_keys: Set[Tuple[int, int]]
    telegraf_host = "localhost"
    telegraf_port = 8125

    def __init__(self):
        PatternMatchingEventHandler.__init__(self, patterns=self.patterns,
                                             ignore_patterns=['cu-cp-cell-1.txt'],
                                             ignore_directories=True, case_sensitive=False)
        self.directory = ''
        self.consumed_keys = set()

    def on_created(self, event):
        super().on_created(event)

    def on_modified(self, event):
        super().on_modified(event)
        # print(event.src_path)

        lock.acquire()
        with open(event.src_path, 'r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                #print(f"The file {event.src_path} has been modified!") 
                timestamp = int(row['timestamp'])
                ue_imsi = int(row['ueImsiComplete'])
                key = (timestamp, ue_imsi)
                if key not in self.consumed_keys:
                    if key not in self.kpm_map:
                         self.kpm_map[key] = [None, None, None]

                    '''not necessary now'''
                    '''if 'L3 serving Id(m_cellId)' in row:
                        sinr = float(row['L3 serving Id(m_cellId)'])
                        self.kpm_map[key][0] = sinr'''

                    if 'DRB.PdcpSduVolumeDl_Filter.UEID (txBytes)' in row:
                        tx_bytes = float(row['DRB.PdcpSduVolumeDl_Filter.UEID (txBytes)'])
                        self.kpm_map[key][1] = tx_bytes

                    if 'DRB.PdcpSduDelayDl.UEID (pdcpLatency)' in row:
                        pdcp_latency = float(row['DRB.PdcpSduDelayDl.UEID (pdcpLatency)'])
                        self.kpm_map[key][2] = pdcp_latency

                    # check if both have been filled and send the data to telegraf
                    if self.kpm_map[key][1] is not None and self.kpm_map[key][2] is not None:
                        self.consumed_keys.add(key)
                        self.send_to_telegraf(tx_bytes=self.kpm_map[key][1], pdcp_latency=self.kpm_map[key][2])
                
        lock.release()

    def on_closed(self, event):
        super().on_closed(event)

    def send_to_telegraf(self, tx_bytes, pdcp_latency):
        # connect to Telegraf
        statsd_client = StatsClient(self.telegraf_host, self.telegraf_port, prefix = None)

        # collect data and send it to telegraf
        pipe = statsd_client.pipeline()
        pipe.gauge(stat='tx_bytes', value=tx_bytes)
        pipe.gauge(stat='pdcp_latency', value=pdcp_latency)
        time.sleep(5)
        pipe.send()
        statsd_client.close()
        
        
if __name__ == "__main__":
    event_handler = SimWatcher()
    observer = Observer()
    observer.schedule(event_handler, ".", False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    
    observer.join()
        