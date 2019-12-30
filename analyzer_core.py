#!/usr/bin/env python3

# This file is Copyright (c) 2017-2019 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

import sys

from migen import *

from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *

from liteiclink.transceiver.gtp_7series import GTPQuadPLL, GTP

# IOs ----------------------------------------------------------------------------------------------

_io = [
    # Clk / Rst
    ("clk200", 0,
        Subsignal("p", Pins(1)),
        Subsignal("n", Pins(1)),
    ),

    ("rst", 0, Pins(1)),

    # PCIe
    ("pcie_refclk", 0,
        Subsignal("p", Pins(1)),
        Subsignal("n", Pins(1))
    ),

    ("pcie_tx", 0,
        Subsignal("p", Pins(1)),
        Subsignal("n", Pins(1))
    ),
    ("pcie_rx", 0,
        Subsignal("p", Pins(1)),
        Subsignal("n", Pins(1))
    ),

    ("pcie_tx", 1,
        Subsignal("p", Pins(1)),
        Subsignal("n", Pins(1))
    ),
    ("pcie_rx", 1,
        Subsignal("p", Pins(1)),
        Subsignal("n", Pins(1))
    ),

    # Analyzer
    ("analyzer", 0,
        Subsignal("clk",  Pins(1)),
        Subsignal("rst",  Pins(1)),
        Subsignal("ctrl", Pins(2)),
        Subsignal("data", Pins(16))
    ),

    ("analyzer", 1,
        Subsignal("clk",  Pins(1)),
        Subsignal("rst",  Pins(1)),
        Subsignal("ctrl", Pins(2)),
        Subsignal("data", Pins(16))
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
        rst    = platform.request("rst")
        platform.add_period_constraint(clk200.p, 1e9/200e6)

        self.submodules.pll = pll = S7PLL()
        self.comb += pll.reset.eq(rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        pll.create_clkout(self.cd_clk125, 125e6)


class AnalyzerCore(SoCMini):
    def __init__(self, platform, connector="pcie", linerate=2.5e9, use_pcie_refclk=True, with_loopback=True):
        assert connector in ["pcie"]
        sys_clk_freq = int(100e6)

        # SoCMini ----------------------------------------------------------------------------------
        SoCMini.__init__(self, platform, sys_clk_freq)

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq)
        platform.add_period_constraint(self.crg.cd_sys.clk, 1e9/100e6)

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

        for i in range(2):
            # GTP --------------------------------------------------------------------------------------
            tx_pads = platform.request(connector + "_tx", i)
            rx_pads = platform.request(connector + "_rx", i)
            gtp = GTP(qpll, tx_pads, rx_pads, sys_clk_freq,
                data_width       = 20,
                clock_aligner    = False,
                tx_buffer_enable = True,
                rx_buffer_enable = True)
            gtp.add_stream_endpoints()
            setattr(self.submodules, "gtp"+str(i), gtp)
            if with_loopback:
                self.comb += gtp.loopback.eq(0b010) # Near-End PMA Loopback
            platform.add_period_constraint(gtp.cd_tx.clk, 1e9/gtp.tx_clk_freq)
            platform.add_period_constraint(gtp.cd_rx.clk, 1e9/gtp.rx_clk_freq)
            self.platform.add_false_path_constraints(
                self.crg.cd_sys.clk,
                gtp.cd_tx.clk,
                gtp.cd_rx.clk)


            # Redirect GTP RX to Analyzer pins  ----------------------------------------------------
            analyzer = platform.request("analyzer", i)
            self.comb += [
                analyzer.clk.eq(gtp.cd_rx.clk),
                analyzer.rst.eq(gtp.cd_rx.rst),
                analyzer.ctrl.eq(gtp.source.ctrl),
                analyzer.data.eq(gtp.source.data),
            ]

# Build --------------------------------------------------------------------------------------------

def main():
    platform = Platform()
    soc     = AnalyzerCore(platform)
    builder = Builder(soc, output_dir="build", compile_gateware=False)
    builder.build(build_name="analyzer_core")

if __name__ == "__main__":
    main()
