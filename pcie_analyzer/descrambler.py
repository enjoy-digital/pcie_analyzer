# This file is Copyright (c) 2020 Franck Jullien <franck.jullien@gmail.com>
# License: BSD

from migen import *
from litex.soc.interconnect import stream

descrambler_layout = [
    ("data", 16),
    ("ctrl", 2),
    ("osets", 2), 
    ("type", 4)
]

# Helpers ------------------------------------------------------------------------------------------

def K(x, y):
    """K code generator ex: K(28, 5) is COM Symbol"""
    return (y << 5) | x

# LFSR -----------------------------------------------------------------------------------

class lfsr(Module):
    """Scrambler Unit

    This module generates the scrambled datas for the PCIe link (X^16 + X^5 + X^4 + X^3 + 1 polynom).
    """
    def __init__(self, reset=0xffff):
        self.value = Signal(16, reset = reset)

        # # #

        self.next1 = Signal(16)
        self.next2 = Signal(16)

        self.comb += [
            self.next1[0].eq(self.value[8]),
            self.next1[1].eq(self.value[9]),
            self.next1[2].eq(self.value[10]),
            self.next1[3].eq(self.value[11] ^ self.value[8]),
            self.next1[4].eq(self.value[12] ^ self.value[9] ^ self.value[8]),
            self.next1[5].eq(self.value[13] ^ self.value[10] ^ self.value[9] ^ self.value[8]),
            self.next1[6].eq(self.value[14] ^ self.value[11] ^ self.value[10] ^ self.value[9]),
            self.next1[7].eq(self.value[15] ^ self.value[12] ^ self.value[11] ^ self.value[10]),

            # Value to be xored
            self.next1[8].eq(self.value[0] ^ self.value[13] ^ self.value[12] ^ self.value[11]),
            self.next1[9].eq(self.value[1] ^ self.value[14] ^ self.value[13] ^ self.value[12]),
            self.next1[10].eq(self.value[2] ^ self.value[15] ^ self.value[14] ^ self.value[13]),
            self.next1[11].eq(self.value[3] ^ self.value[15] ^ self.value[14]),
            self.next1[12].eq(self.value[4] ^ self.value[15]),
            self.next1[13].eq(self.value[5]),
            self.next1[14].eq(self.value[6]),
            self.next1[15].eq(self.value[7]),

            self.next2[0].eq(self.next1[8]),
            self.next2[1].eq(self.next1[9]),
            self.next2[2].eq(self.next1[10]),
            self.next2[3].eq(self.next1[11] ^ self.next1[8]),
            self.next2[4].eq(self.next1[12] ^ self.next1[9] ^ self.next1[8]),
            self.next2[5].eq(self.next1[13] ^ self.next1[10] ^ self.next1[9] ^ self.next1[8]),
            self.next2[6].eq(self.next1[14] ^ self.next1[11] ^ self.next1[10] ^ self.next1[9]),
            self.next2[7].eq(self.next1[15] ^ self.next1[12] ^ self.next1[11] ^ self.next1[10]),

            # Value to be xored
            self.next2[8].eq(self.next1[0] ^ self.next1[13] ^ self.next1[12] ^ self.next1[11]),
            self.next2[9].eq(self.next1[1] ^ self.next1[14] ^ self.next1[13] ^ self.next1[12]),
            self.next2[10].eq(self.next1[2] ^ self.next1[15] ^ self.next1[14] ^ self.next1[13]),
            self.next2[11].eq(self.next1[3] ^ self.next1[15] ^ self.next1[14]),
            self.next2[12].eq(self.next1[4] ^ self.next1[15]),
            self.next2[13].eq(self.next1[5]),
            self.next2[14].eq(self.next1[6]),
            self.next2[15].eq(self.next1[7]),
        ]

class Descrambler(Module):
    """Descrambler

    This module descrambles the RX data/ctrl stream. K codes and TS1/TS2 data shall not be descrambled.
    The descrambler automatically synchronizes itself to the incoming stream and resets the lfsr unit
    when COM characters are seen.
    """

    def __init__(self):
        self.sink   =   sink = stream.Endpoint(descrambler_layout)
        self.source = source = stream.Endpoint(descrambler_layout)

        # # #

        LFSR_VALUE_NEXT_AFTER_RESET = 0xE817
        LFSR_VALUE_RESET = 0xFFFF

        self.submodules.lfsr = lfsr()

        self.sync += [

            self.source.type.eq(self.sink.type),
            self.source.ctrl.eq(self.sink.ctrl),
            self.source.osets.eq(self.sink.osets),

            If(self.sink.ctrl == 0b00,

                *[self.source.data[i+8].eq(self.sink.data[i+8] ^ self.lfsr.value[15-i]) for i in range(8)],
                *[self.source.data[i].eq(self.sink.data[i]     ^ self.lfsr.next1[15-i]) for i in range(8)],

                self.lfsr.value.eq(self.lfsr.next2)
            ),

            If(self.sink.ctrl == 0b01,

                # First byte is a DATA
                *[self.source.data[i+8].eq(self.sink.data[i+8] ^ self.lfsr.value[15-i]) for i in range(8)],

                # Second byte is not scrambled
                self.source.data[0:8].eq(self.sink.data[0:8]),

                # Second byte is a COMMA
                If(self.sink.data[0:8] == K(28, 5),
                    self.lfsr.value.eq(LFSR_VALUE_RESET)

                # Second byte is a SKIP
                ).Else(If(self.sink.data[0:8] == K(28, 0),
                        self.lfsr.value.eq(self.lfsr.next1),

                # Second byte is another K symbol
                ).Else(
                        self.lfsr.value.eq(self.lfsr.next2),
                ))
            ),

            If(self.sink.ctrl == 0b10,

                # Second byte is a DATA
                *[self.source.data[i].eq(self.sink.data[i] ^ self.lfsr.value[15-i]) for i in range(8)],

                # First byte is not scrambled
                self.source.data[8:16].eq(self.sink.data[8:16]),

                # First byte is a COMMA
                If(self.sink.data[8:16] == K(28, 5),
                    self.source.data[0:8].eq(self.sink.data[0:8] ^ 0xFF),
                    self.lfsr.value.eq(LFSR_VALUE_NEXT_AFTER_RESET)

                # First byte is a SKIP
                ).Else(If(self.sink.data[8:16] == K(28, 0),
                        self.lfsr.value.eq(self.lfsr.next1),

                # First byte is another K symbol
                ).Else(
                        self.lfsr.value.eq(self.lfsr.next2),
                ))
            ),

            If(self.sink.ctrl == 0b11,

                # First and sedcond byte are not scrambled
                self.source.data.eq(self.sink.data),

                # First byte is a COMMA
                If(self.sink.data[8:16] == K(28, 5),

                    # Second byte is a COMMA
                    If(self.sink.data[0:8] == K(28, 5),
                        self.lfsr.value.eq(LFSR_VALUE_RESET)

                    # Second byte is a SKIP
                    ).Else(If(self.sink.data[0:8] == K(28, 0),
                            self.lfsr.value.eq(LFSR_VALUE_RESET)

                    # Second byte is another K symbol
                    ).Else(
                            self.lfsr.value.eq(LFSR_VALUE_NEXT_AFTER_RESET)
                    ))
                ),

                # First byte is a SKIP
                If(self.sink.data[8:16] == K(28, 0),

                    # Second byte is a COMMA
                    If(self.sink.data[0:8] == K(28, 5),
                        self.lfsr.value.eq(LFSR_VALUE_RESET)

                    # Second byte is a SKIP
                    ).Else(If((self.sink.data[0:8] != K(28, 5)) & (self.sink.data[0:8] != K(28, 0)),
                            self.lfsr.value.eq(self.lfsr.next1)
                    ))
                ),

                # First byte is not a SKIP or a COMMA
                If((self.sink.data[8:16] != K(28, 5)) & (self.sink.data[8:16] != K(28, 0)),

                    # Second byte is a COMMA
                    If(self.sink.data[0:8] == K(28, 5),
                        self.lfsr.value.eq(LFSR_VALUE_RESET)

                    # Second byte is a SKIP
                    ).Else(If(self.sink.data[0:8] == K(28, 0),
                            self.lfsr.value.eq(self.lfsr.next1)

                    # Second byte is another K symbol
                    ).Else(
                           self.lfsr.value.eq(self.lfsr.next2)
                    ))
                )
            ),

            If(self.sink.osets[0],
                self.source.data[0:8].eq(self.sink.data[0:8])
            ),

            If(self.sink.osets[1],
                self.source.data[8:16].eq(self.sink.data[8:16])
            ),

        ]

        self.comb == [
            self.source.valid.eq(self.source.ready),
            self.sink.ready.eq(1),
        ]
