#!/usr/bin/env python3

# This file is Copyright (c) 2020 Franck Jullien <franck.jullien@gmail.com>
# License: BSD

import csv

from migen import *
from migen.fhdl import *

from litex.soc.interconnect.stream import *
from litex.soc.interconnect.stream_sim import *

from descrambler import *

values=[]

def load_values(dump):
    first = True
    f = open(dump, "r")
    reader = csv.reader(f)
    for row in reader:
        if first:
            first = False
            continue
        data = int('0x' + row[5], 16)
        #print("data = " + str(data))
        ctrl = int('0x' + row[4], 16)
        #print("datak = " + str(ctrl))
        values.append((ctrl << 16) + data)


class TB(Module):
    def __init__(self):
        self.submodules.streamer = PacketStreamer([("data", 18)])

        self.submodules.descrambler = Descrambler()
        self.submodules.detect = DetectOrderedSets()

        self.comb += [
        
            self.detect.sink.data.eq(self.streamer.source.data[0:16]),
            self.detect.sink.ctrl.eq(self.streamer.source.data[16:18]),
        
            self.streamer.source.ready.eq(1),
            self.descrambler.sink.valid.eq(1),
            self.descrambler.sink.data.eq(self.detect.source.data),
            self.descrambler.sink.ctrl.eq(self.detect.source.ctrl),
            self.descrambler.sink.osets.eq(self.detect.source.osets),
            self.descrambler.sink.type.eq(self.detect.source.type),
            self.descrambler.source.ready.eq(1),
        ]

def main_generator(dut):
    load_values("/home/franck/Dropbox/RTL/analyzer/analyzer_hw_github/srcs/simu/simple.csv")
    packet = Packet(values)
    dut.streamer.send(packet)

    for i in range(1000):
        if i == 100:
            yield dut.descrambler.sink.osets.eq(3)
        if i == 105:
            yield dut.descrambler.sink.osets.eq(0)
        yield

if __name__ == "__main__":
    tb = TB()
    generators = {
        "sys" :   [main_generator(tb),
                   tb.streamer.generator()]
    }
    clocks = {"sys": 10}

    #print(verilog.convert(tb))

    run_simulation(tb, generators, clocks, vcd_name="sim.vcd")
