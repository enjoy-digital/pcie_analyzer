#!/usr/bin/env python3

# This file is Copyright (c) 2017-2019 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

import sys

from migen import *

from litex_boards.platforms import ac701

from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *

from liteiclink.transceiver.gtp_7series import GTPQuadPLL, GTP

# IOs ----------------------------------------------------------------------------------------------

_io = [
    ("clk200", 0,
        Subsignal("p", Pins("R3"), IOStandard("DIFF_SSTL15")),
        Subsignal("n", Pins("P3"), IOStandard("DIFF_SSTL15"))
    ),

    ("cpu_reset", 0, Pins("U4"), IOStandard("SSTL15")),

    ("user_led", 0, Pins("M26"), IOStandard("LVCMOS33")),
    ("user_led", 1, Pins("T24"), IOStandard("LVCMOS33")),
    ("user_led", 2, Pins("T25"), IOStandard("LVCMOS33")),
    ("user_led", 3, Pins("R26"), IOStandard("LVCMOS33")),


    ("pcie_refclk", 0,
        Subsignal("p", Pins("F11")),
        Subsignal("n", Pins("E11"))
    ),

    ("pcie_tx", 0,
        Subsignal("p", Pins("D10")),
        Subsignal("n", Pins("C10"))
    ),
    ("pcie_rx", 0,
        Subsignal("p", Pins("D12")),
        Subsignal("n", Pins("C12"))
    ),
]


# Platform -----------------------------------------------------------------------------------------

class Platform(XilinxPlatform):
    def __init__(self):
        XilinxPlatform.__init__(self, "xc7a200t-fbg676-2", _io, toolchain="vivado")

# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq):
        self.clock_domains.cd_sys    = ClockDomain()
        self.clock_domains.cd_clk125 = ClockDomain()

        # # #

        clk200 = platform.request("clk200")
        rst    = platform.request("cpu_reset")
        platform.add_period_constraint(clk200.p, 1e9/200e6)

        self.submodules.pll = pll = S7PLL()
        self.comb += pll.reset.eq(rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        pll.create_clkout(self.cd_clk125, 125e6)


class GTPTestSoC(SoCMini):
    def __init__(self, platform, connector="pcie", linerate=2.5e9, use_pcie_refclk=True, with_loopback=True):
        assert connector in ["pcie"]
        sys_clk_freq = int(100e6)

        # SoCMini ----------------------------------------------------------------------------------
        SoCMini.__init__(self, platform, sys_clk_freq)

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq)

        # GTP RefClk -------------------------------------------------------------------------------
        if use_pcie_refclk:
            refclk      = Signal()
            refclk_freq = 100e6
            refclk_pads = platform.request("pcie_refclk")
            self.specials += Instance("IBUFDS_GTE2",
                i_CEB   = 0,
                i_I     = refclk_pads.p,
                i_IB    = refclk_pads.n,
                o_O     = refclk)
        else:
            refclk      = Signal()
            refclk_freq = 125e6
            self.comb += refclk.eq(ClockSignal("clk125"))
            platform.add_platform_command("set_property SEVERITY {{Warning}} [get_drc_checks REQP-49]")

        # GTP PLL ----------------------------------------------------------------------------------
        qpll = GTPQuadPLL(refclk, refclk_freq, linerate)
        print(qpll)
        self.submodules += qpll

        # GTP --------------------------------------------------------------------------------------
        tx_pads = platform.request(connector + "_tx")
        rx_pads = platform.request(connector + "_rx")
        gtp = GTP(qpll, tx_pads, rx_pads, sys_clk_freq,
            data_width       = 20,
            clock_aligner    = False,
            tx_buffer_enable = True,
            rx_buffer_enable = True)
        self.submodules += gtp
        if with_loopback:
            self.comb += gtp.loopback.eq(0b010) # Near-End PMA Loopback

        platform.add_period_constraint(self.crg.cd_sys.clk, 1e9/100e6)
        platform.add_period_constraint(gtp.cd_tx.clk, 1e9/gtp.tx_clk_freq)
        platform.add_period_constraint(gtp.cd_rx.clk, 1e9/gtp.rx_clk_freq)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            gtp.cd_tx.clk,
            gtp.cd_rx.clk)

        # Test -------------------------------------------------------------------------------------
        counter = Signal(32)
        self.sync.tx += counter.eq(counter + 1)

        # K28.5 and slow counter --> TX
        self.comb += [
            gtp.encoder.k[0].eq(1),
            gtp.encoder.d[0].eq((5 << 5) | 28),
            gtp.encoder.k[1].eq(0),
            gtp.encoder.d[1].eq(counter[26:]),
        ]

       # RX (slow counter) --> Leds
        for i in range(4):
            self.comb += platform.request("user_led", i).eq(gtp.decoders[1].d[i])

# Load ---------------------------------------------------------------------------------------------

def load():
    from litex.build.xilinx import VivadoProgrammer
    prog = VivadoProgrammer()
    prog.load_bitstream("build/gateware/ac701.bit")
    exit()

# Build --------------------------------------------------------------------------------------------

def main():
    if "load" in sys.argv[1:]:
        load()
    platform = Platform()
    soc     = GTPTestSoC(platform)
    builder = Builder(soc, output_dir="build")
    builder.build(build_name="ac701")

if __name__ == "__main__":
    main()
