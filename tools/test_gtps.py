#!/usr/bin/env python3

import sys
import time

from litex import RemoteClient

wb = RemoteClient()
wb.open()

# # #

class BIST:
    def __init__(self, tx_name, rx_name):
        self._tx_enable = getattr(wb.regs, tx_name + "_enable")
        self._rx_enable = getattr(wb.regs, rx_name + "_enable")
        self._rx_errors = getattr(wb.regs, rx_name + "_errors")

    def run(self):
        self._tx_enable.write(0)
        self._rx_enable.write(0)
        self._tx_enable.write(1)
        time.sleep(0.1)
        self._rx_enable.write(1)
        time.sleep(1)
        return self._rx_errors.read()

print("GTP0 TX Clk: {:d}".format(wb.regs.gtp0_tx_freq_value.read()))
print("GTP0 RX Clk: {:d}".format(wb.regs.gtp0_rx_freq_value.read()))
print("GTP0 TX Clk: {:d}".format(wb.regs.gtp1_tx_freq_value.read()))
print("GTP0 RX Clk: {:d}".format(wb.regs.gtp1_rx_freq_value.read()))

print("Running GTP0 BIST...")
gtp0_bist = BIST("gtp0_tx_bist", "gtp0_rx_bist")
errors = gtp0_bist.run()
print("Errors: {}".format(errors))

print("Running GTP1 BIST...")
gtp1_bist = BIST("gtp1_tx_bist", "gtp1_rx_bist")
errors = gtp1_bist.run()
print("Errors: {}".format(errors))

# # #

wb.close()
