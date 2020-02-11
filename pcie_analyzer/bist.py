# This file is Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

from migen import *
from migen.genlib.cdc import MultiReg

from litex.soc.interconnect.csr import *


class GTPTXBIST(Module, AutoCSR):
    def __init__(self, gtp, cd):
        self.enable = CSRStorage()

        # # #

        enable = Signal()
        self.specials += MultiReg(self.enable.storage, enable, cd)

        counter = Signal(32)
        self.comb += [
            If(enable,
                gtp.sink.valid.eq(1),
                gtp.loopback.eq(0b010)
            ),
            gtp.sink.data.eq(counter)
        ]
        sync = getattr(self.sync, cd)
        sync += If(gtp.sink.ready, counter.eq(counter + 1))


class GTPRXBIST(Module, AutoCSR):
    def __init__(self, gtp, cd):
        self.enable = CSRStorage()
        self.errors = CSRStatus(32)

        # # #

        enable = Signal()
        errors = Signal(32)
        self.specials += MultiReg(self.enable.storage, enable, cd)
        self.specials += MultiReg(errors, self.errors.status, "sys")

        data_last = Signal(16)
        data_next = Signal(16)
        self.comb += data_next.eq(data_last + 1)
        sync = getattr(self.sync, cd)
        sync += [
            If(~enable,
                errors.eq(0)
            ),
            data_last.eq(gtp.source.data),
            If(data_next != gtp.source.data,
                errors.eq(errors + 1)
            )
        ]
