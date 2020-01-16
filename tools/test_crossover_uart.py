#!/usr/bin/env python3

import sys

from litex import RemoteClient

wb = RemoteClient()
wb.open()

# # #

while True:
    if wb.regs.uart_xover_rxempty.read() == 0:
        print(chr(wb.regs.uart_xover_rxtx.read()), end="")
        sys.stdout.flush()

# # #

wb.close()
