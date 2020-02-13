# This file is Copyright (c) 2019 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

from migen import *

from litex.soc.interconnect import stream

# Helpers ------------------------------------------------------------------------------------------

def K(x, y):
    """K code generator ex: K(28, 5) is COM Symbol"""
    return (y << 5) | x

# RX SKP Remover ------- ---------------------------------------------------------------------------

class RXSKPRemover(Module):
    """RX SKP Remover

    SKP Ordered Sets are inserted in the stream for clock compensation between partners with an
    average of 1 SKP Ordered Set every 354 symbols. This module removes SKP Ordered Sets from
    the RX stream.
    """
    def __init__(self):
        self.sink   = sink   = stream.Endpoint([("data", 32), ("ctrl", 4)])
        self.source = source = stream.Endpoint([("data", 32), ("ctrl", 4)])
        self.skip   = Signal()

        # # #

        # Find SKP symbols -------------------------------------------------------------------------
        skp = Signal(4)
        for i in range(4):
            self.comb += skp[i].eq(sink.ctrl[i] & (sink.data[8*i:8*(i+1)] == K(28, 1)))
        self.comb += self.skip.eq(self.sink.valid & self.sink.ready & (skp != 0))

        # Select valid Data/Ctrl fragments ---------------------------------------------------------
        frag_data  = Signal(32)
        frag_ctrl  = Signal(4)
        frag_bytes = Signal(3)
        cases = {}
        for i in range(2**4):
            datas = []
            ctrls = []
            for j in range(4):
                if (i & 2**j) == 0:
                    datas.append(sink.data[8*j:8*(j+1)])
                    ctrls.append(sink.ctrl[1*j:1*(j+1)])
            cases[i] = [
                frag_data.eq(Cat(*datas) if len(datas) else 0),
                frag_ctrl.eq(Cat(*ctrls) if len(ctrls) else 0),
                frag_bytes.eq(len(ctrls)),
            ]
        self.comb += Case(skp, cases)

        # Store Data/Ctrl in a 64/8-bit Shift Register ---------------------------------------------
        sr_data  = Signal(64)
        sr_ctrl  = Signal(8)
        sr_bytes = Signal(4)
        cases = {}
        cases[0] = [
            sr_data.eq(sr_data),
            sr_ctrl.eq(sr_ctrl),
        ]
        for i in range(1, 5):
            cases[i] = [
                sr_data.eq(Cat(sr_data[8*i:], frag_data[0:8*i])),
                sr_ctrl.eq(Cat(sr_ctrl[1*i:], frag_ctrl[0:1*i])),
            ]
        self.comb += sink.ready.eq(sr_bytes <= 7)
        self.sync += [
            If(sink.valid & sink.ready,
                If(source.valid & source.ready,
                    sr_bytes.eq(sr_bytes + frag_bytes - 4)
                ).Else(
                    sr_bytes.eq(sr_bytes + frag_bytes)
                ),
                Case(frag_bytes, cases)
            ).Elif(source.valid & source.ready,
                sr_bytes.eq(sr_bytes - 4)
            )
        ]

        # Output Data/Ctrl when there is a full 32/4-bit word --------------------------------------
        self.comb += source.valid.eq(sr_bytes >= 4)
        cases = {}
        for i in range(4, 8):
            cases[i] = [
                source.data.eq(sr_data[8*(8-i):8*(8-i+4)]),
                source.ctrl.eq(sr_ctrl[1*(8-i):1*(8-i+4)]),
            ]
        self.comb += Case(sr_bytes, cases)
