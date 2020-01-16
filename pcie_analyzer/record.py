# This file is Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

from migen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect import stream

from litedram.frontend.dma import LiteDRAMDMAWriter

# Recorder -----------------------------------------------------------------------------------------

class Recorder(Module, AutoCSR):
    def __init__(self, dram_port, clock_domain):
        self.start  = CSR()
        self.done   = CSRStatus()
        self.base   = CSRStorage(32)
        self.length = CSRStorage(32)

        self.sink = stream.Endpoint([("data", 32)])

        # # #

        count = Signal(32)

        # Clock domain crossing
        cdc = stream.AsyncFIFO([("data", 32)], 8, buffered=True)
        cdc = ClockDomainsRenamer({"write": clock_domain, "read": "sys"})(cdc)
        self.submodules.cdc = cdc
        self.comb += self.sink.connect(cdc.sink)

        # DMA
        dma_writer = LiteDRAMDMAWriter(dram_port)
        self.submodules += dma_writer

        # FSM
        self.submodules.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            self.done.status.eq(1),
            If(self.start.re,
                NextValue(count, 0),
                NextState("RUN")
            )
        )
        fsm.act("RUN",
            cdc.source.connect(dma_writer.sink),
            dma_writer.sink.address.eq(self.base.storage + count),
            If(dma_writer.sink.valid & dma_writer.sink.ready,
                NextValue(count, count + 1),
                If(count == (self.length.storage - 1),
                    NextState("IDLE")
                )
            )
        )
