# This file is Copyright (c) 2020 Franck Jullien <franck.jullien@gmail.com>
# License: BSD

from migen import *
from litex.soc.interconnect import stream
from enum import IntEnum

class osetsType(IntEnum):
    DATA = 0
    SKIP = 1
    IDLE = 2
    FTS  = 3
    TS1  = 4
    TS2  = 5
    COMPLIANCE = 6
    MODIFIED_COMPLIANCE = 7

# Helpers ------------------------------------------------------------------------------------------

def K(x, y):
    """K code generator ex: K(28, 5) is COM Symbol"""
    return (y << 5) | x

def D(x, y):
    """D code generator ex: D(10, 2) is TS1 ID Symbol"""
    return (y << 5) | x

def TWO(x):
    """Put x in both lower and upper nibble of a short"""
    return (x << 8) + x

# Detector ------------------------------------------------------------------------------------------

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

        UPPER_BYTE = slice(8,16)
        LOWER_BYTE = slice(0,8)
        DATA_WORD  = slice(0,16)
        UPPER_K    = 17
        LOWER_K    = 16

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
            self.source.valid.eq(1),
            self.sink.ready.eq(1),
            self.source.data.eq(self.word9[DATA_WORD]),
            self.source.ctrl.eq(self.word9[16:18]),
        ]
