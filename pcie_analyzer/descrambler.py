# This file is Copyright (c) 2020 Franck Jullien <franck.jullien@gmail.com>
# License: BSD

from migen import *
from litex.soc.interconnect import stream
from enum import IntEnum

# *********************************************************
# *                                                       *
# *                     Definitions                       *
# *                                                       *
# *********************************************************

class osetsType(IntEnum):
    DATA = 0
    SKIP = 1
    IDLE = 2
    FTS  = 3
    TS1  = 4
    TS2  = 5
    COMPLIANCE = 6
    MODIFIED_COMPLIANCE = 7

descrambler_layout = [
    ("data", 16),
    ("ctrl", 2),
    ("osets", 2),
    ("type", 4)
]

UPPER_BYTE = slice(8,16)
LOWER_BYTE = slice(0,8)
DATA_WORD  = slice(0,16)
UPPER_K    = 17
LOWER_K    = 16

# *********************************************************
# *                                                       *
# *                      Helpers                          *
# *                                                       *
# *********************************************************

def K(x, y):
    """K code generator ex: K(28, 5) is COM Symbol"""
    return (y << 5) | x

def D(x, y):
    """D code generator ex: D(10, 2) is TS1 ID Symbol"""
    return (y << 5) | x

def TWO(x):
    """Put x in both lower and upper nibble of a short"""
    return (x << 8) + x

# *********************************************************
# *                                                       *
# *                         LFSR                          *
# *                                                       *
# *********************************************************

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

# *********************************************************
# *                                                       *
# *              Ordered Sets Detector                    *
# *                                                       *
# *********************************************************

class DetectOrderedSets(Module):
    """DetectOrderedSets

    Detect ordered sets type.
    """

    def __init__(self):
        self.source = source = stream.Endpoint([("data", 16), ("ctrl", 2), ("osets", 2), ("type", 4)])
        self.sink   = sink   = stream.Endpoint([("data", 16), ("ctrl", 2)])

        # # #

        osets_pattern = Signal(16)

        self.word0 = Signal(18)
        self.word1 = Signal(18)
        self.word2 = Signal(18)
        self.word3 = Signal(18)
        self.word4 = Signal(18)
        self.word5 = Signal(18)
        self.word6 = Signal(18)
        self.word7 = Signal(18)
        self.word8 = Signal(18)
        self.word9 = Signal(18)

        self.sync += [

            # Generates osets bits during ordered sets detection
            If(osets_pattern[14:16] != 0,
                self.source.osets.eq(osets_pattern[14:16]),
                osets_pattern.eq(Cat(0, 0, osets_pattern[0:15])),
            ).Else(
                self.source.osets.eq(0b00),
                self.source.type.eq(osetsType.DATA),
            ),

            # Shift register containing ordered sets (swap DATA bytes order)
            self.word0.eq(Cat(sink.data[UPPER_BYTE], sink.data[LOWER_BYTE], sink.ctrl[1], sink.ctrl[0])),
            self.word1.eq(self.word0),
            self.word2.eq(self.word1),
            self.word3.eq(self.word2),
            self.word4.eq(self.word3),
            self.word5.eq(self.word4),
            self.word6.eq(self.word5),
            self.word7.eq(self.word6),
            self.word8.eq(self.word7),
            self.word9.eq(self.word8),

            # COMMA is in upper nibble
            If((self.word8[UPPER_BYTE] == K(28,5)) & self.word8[UPPER_K],

                # If SKIP, SKIP, SKIP
                If((self.word8[LOWER_BYTE] == K(28,0)) & (self.word7[DATA_WORD] == TWO(K(28,0))),

                    self.source.osets.eq(0b11),
                    self.source.type.eq(osetsType.SKIP),
                    osets_pattern.eq(0b1100000000000000),
                ),

                # If IDLE, IDLE, IDLE
                If((self.word8[LOWER_BYTE] == K(28,3)) & (self.word7[DATA_WORD] == TWO(K(28,3))),

                    self.source.osets.eq(0b11),
                    self.source.type.eq(osetsType.IDLE),
                    osets_pattern.eq(0b1100000000000000),
                ),

                # If FTS, FTS, FTS
                If((self.word8[LOWER_BYTE] == K(28,1)) & (self.word7[DATA_WORD] == TWO(K(28,1))),

                    self.source.osets.eq(0b11),
                    self.source.type.eq(osetsType.FTS),
                    osets_pattern.eq(0b1100000000000000),
                ),

                # If TS1
                If((self.word5[DATA_WORD] == TWO(D(10,2))) &
                   (self.word4[DATA_WORD] == TWO(D(10,2))) &
                   (self.word3[DATA_WORD] == TWO(D(10,2))) &
                   (self.word2[DATA_WORD] == TWO(D(10,2))) &
                   (self.word1[DATA_WORD] == TWO(D(10,2))),

                    self.source.osets.eq(0b11),
                    self.source.type.eq(osetsType.TS1),
                    osets_pattern.eq(0b1111111111111100),
                ),

                # If TS2
                If((self.word5[DATA_WORD] == TWO(D(5,2))) &
                   (self.word4[DATA_WORD] == TWO(D(5,2))) &
                   (self.word3[DATA_WORD] == TWO(D(5,2))) &
                   (self.word2[DATA_WORD] == TWO(D(5,2))) &
                   (self.word1[DATA_WORD] == TWO(D(5,2))),

                    self.source.osets.eq(0b11),
                    self.source.type.eq(osetsType.TS2),
                    osets_pattern.eq(0b1111111111111100),
                ),

                # If COMPLIANCE (COMMA, D21.5, COMMA, D10.2, ERROR_SYM, ERROR_SIM, COMMA, COMMA)
                If((self.word8[LOWER_BYTE]  == D(21,5)) &
                   (self.word7[UPPER_BYTE] == K(28,5)) &
                   (self.word7[LOWER_BYTE]  == D(10,2)) &
                   (self.word5[UPPER_BYTE] == K(28,5)) &
                   (self.word5[LOWER_BYTE]  == K(28,5)),

                    self.source.osets.eq(0b11),
                    self.source.type.eq(osetsType.MODIFIED_COMPLIANCE),
                    osets_pattern.eq(0b1111110000000000),
                ).Else (

                    # If COMPLIANCE (COMMA, D21.5, COMMA, D10.2)
                    If((self.word8[LOWER_BYTE]  == D(21,5)) &
                       (self.word7[UPPER_BYTE] == K(28,5)) &
                       (self.word7[LOWER_BYTE]  == D(10,2)),

                        self.source.osets.eq(0b11),
                        self.source.type.eq(osetsType.COMPLIANCE),
                        osets_pattern.eq(0b1100000000000000),
                    ),
                ),
            ),

            # COMMA is in lower nibble
            If((self.word8[LOWER_BYTE] == K(28,5)) & self.word8[LOWER_K],

                # If SKIP, SKIP, SKIP
                If((self.word7[DATA_WORD] == TWO(K(28,0))) & (self.word6[UPPER_BYTE] == K(28,0)),
                    self.source.osets.eq(0b01),
                    self.source.type.eq(osetsType.SKIP),
                    osets_pattern.eq(0b1110000000000000),
                ),

                # If IDLE, IDLE, IDLE
                If((self.word7[DATA_WORD] == TWO(K(28,3))) & (self.word6[UPPER_BYTE] == K(28,3)),
                    self.source.osets.eq(0b01),
                    self.source.type.eq(osetsType.IDLE),
                    osets_pattern.eq(0b1110000000000000),
                ),

                # If FTS, FTS, FTS
                If((self.word7[DATA_WORD] == TWO(K(28,1))) & (self.word6[UPPER_BYTE] == K(28,1)),
                    self.source.osets.eq(0b01),
                    self.source.type.eq(osetsType.FTS),
                    osets_pattern.eq(0b1110000000000000),
                ),

                # If TS1
                If((self.word5[LOWER_BYTE] == D(10,2)) &
                   (self.word4[DATA_WORD]  == TWO(D(10,2))) &
                   (self.word3[DATA_WORD]  == TWO(D(10,2))) &
                   (self.word2[DATA_WORD]  == TWO(D(10,2))) &
                   (self.word1[DATA_WORD]  == TWO(D(10,2))) &
                   (self.word0[UPPER_BYTE] == D(10,2)),

                    self.source.osets.eq(0b11),
                    self.source.type.eq(osetsType.TS1),
                    osets_pattern.eq(0b1111111111111100),
                ),

                # If TS2
                If((self.word5[LOWER_BYTE] == D(5,2)) &
                   (self.word4[DATA_WORD]  == TWO(D(5,2))) &
                   (self.word3[DATA_WORD]  == TWO(D(5,2))) &
                   (self.word2[DATA_WORD]  == TWO(D(5,2))) &
                   (self.word1[DATA_WORD]  == TWO(D(5,2))) &
                   (self.word0[UPPER_BYTE] == D(5,2)),

                    self.source.osets.eq(0b11),
                    self.source.type.eq(osetsType.TS2),
                    osets_pattern.eq(0b1111111111111100),
                ),

                # If COMPLIANCE (COMMA, D21.5, COMMA, D10.2, ERROR_SYM, ERROR_SIM, COMMA, COMMA)
                If((self.word7[UPPER_BYTE] == D(21,5)) &
                   (self.word7[LOWER_BYTE] == K(28,5)) &
                   (self.word6[UPPER_BYTE] == D(10,2)) &
                   (self.word5[LOWER_BYTE] == K(28,5)) &
                   (self.word4[UPPER_BYTE] == K(28,5)),

                    self.source.osets.eq(0b01),
                    self.source.type.eq(osetsType.MODIFIED_COMPLIANCE),
                    osets_pattern.eq(0b1111111000000000),
                ).Else (

                    # If COMPLIANCE (COMMA, D21.5, COMMA, D10.2
                    If((self.word7[UPPER_BYTE] == D(21,5)) &
                       (self.word7[LOWER_BYTE] == K(28,5)) &
                       (self.word6[UPPER_BYTE] == D(10,2)),

                        self.source.osets.eq(0b01),
                        self.source.type.eq(osetsType.COMPLIANCE),
                        osets_pattern.eq(0b1110000000000000),
                    ),
                ),
            )
        ]

        self.comb += [
            self.source.valid.eq(self.sink.valid),
            self.sink.ready.eq(1),
            If(self.sink.valid,
                self.source.data.eq(self.word9[DATA_WORD]),
                self.source.ctrl.eq(self.word9[16:18]),
            ).Else(
                self.source.data.eq(0),
                self.source.ctrl.eq(0),
            )
        ]

# *********************************************************
# *                                                       *
# *                   Descrambler                         *
# *                                                       *
# *********************************************************

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
                self.source.data[LOWER_BYTE].eq(self.sink.data[LOWER_BYTE]),

                # Second byte is a COMMA
                If(self.sink.data[LOWER_BYTE] == K(28, 5),
                    self.lfsr.value.eq(LFSR_VALUE_RESET)

                # Second byte is a SKIP
                ).Else(If(self.sink.data[LOWER_BYTE] == K(28, 0),
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
                self.source.data[UPPER_BYTE].eq(self.sink.data[UPPER_BYTE]),

                # First byte is a COMMA
                If(self.sink.data[UPPER_BYTE] == K(28, 5),
                    self.source.data[LOWER_BYTE].eq(self.sink.data[LOWER_BYTE] ^ 0xFF),
                    self.lfsr.value.eq(LFSR_VALUE_NEXT_AFTER_RESET)

                # First byte is a SKIP
                ).Else(If(self.sink.data[UPPER_BYTE] == K(28, 0),
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
                If(self.sink.data[UPPER_BYTE] == K(28, 5),

                    # Second byte is a COMMA
                    If(self.sink.data[LOWER_BYTE] == K(28, 5),
                        self.lfsr.value.eq(LFSR_VALUE_RESET)

                    # Second byte is a SKIP
                    ).Else(If(self.sink.data[LOWER_BYTE] == K(28, 0),
                            self.lfsr.value.eq(LFSR_VALUE_RESET)

                    # Second byte is another K symbol
                    ).Else(
                            self.lfsr.value.eq(LFSR_VALUE_NEXT_AFTER_RESET)
                    ))
                ),

                # First byte is a SKIP
                If(self.sink.data[UPPER_BYTE] == K(28, 0),

                    # Second byte is a COMMA
                    If(self.sink.data[LOWER_BYTE] == K(28, 5),
                        self.lfsr.value.eq(LFSR_VALUE_RESET)

                    # Second byte is a SKIP
                    ).Else(If((self.sink.data[LOWER_BYTE] != K(28, 5)) & (self.sink.data[LOWER_BYTE] != K(28, 0)),
                            self.lfsr.value.eq(self.lfsr.next1)
                    ))
                ),

                # First byte is not a SKIP or a COMMA
                If((self.sink.data[UPPER_BYTE] != K(28, 5)) & (self.sink.data[UPPER_BYTE] != K(28, 0)),

                    # Second byte is a COMMA
                    If(self.sink.data[LOWER_BYTE] == K(28, 5),
                        self.lfsr.value.eq(LFSR_VALUE_RESET)

                    # Second byte is a SKIP
                    ).Else(If(self.sink.data[LOWER_BYTE] == K(28, 0),
                            self.lfsr.value.eq(self.lfsr.next1)

                    # Second byte is another K symbol
                    ).Else(
                           self.lfsr.value.eq(self.lfsr.next2)
                    ))
                )
            ),

            If(self.sink.osets[0],
                self.source.data[LOWER_BYTE].eq(self.sink.data[LOWER_BYTE])
            ),

            If(self.sink.osets[1],
                self.source.data[UPPER_BYTE].eq(self.sink.data[UPPER_BYTE])
            ),

        ]

        self.comb == [
            self.source.valid.eq(self.sink.valid & self.source.ready),
            self.sink.ready.eq(1),
        ]
