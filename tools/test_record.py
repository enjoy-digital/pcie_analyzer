#!/usr/bin/env python3

import sys

from litex import RemoteClient

wb = RemoteClient()
wb.open()

# # #

class DMARecorder:
    def __init__(self, name):
        self._start  = getattr(wb.regs, name + "_start")
        self._done   = getattr(wb.regs, name + "_done")
        self._base   = getattr(wb.regs, name + "_base")
        self._length = getattr(wb.regs, name + "_length")

    def capture(self, base, length):
        print("Capture of {} bytes to @0x{:08x}...".format(length, base))
        self._base.write(base)
        self._length.write(length)
        self._start.write(1)
        print("Waiting...")
        while self._done.read() != 1:
            pass
        print("Done...")

    def upload(self, base, length):
        print("Upload of {} bytes to @0x{:08x}...".format(length, base))
        datas = []
        for i in range(length//4):
            datas.append(wb.read(base + 4*i))
        return datas

rx_recorder = DMARecorder("rx_dma_recorder")
rx_recorder.capture(0x0000, 32)
datas = rx_recorder.upload(wb.mems.main_ram.base, 32)
for data in datas:
    print("{:08x}".format(data))

tx_recorder = DMARecorder("tx_dma_recorder")
tx_recorder.capture(0x0000, 32)
datas = tx_recorder.upload(wb.mems.main_ram.base, 32)
for data in datas:
    print("{:08x}".format(data))

# # #

wb.close()
