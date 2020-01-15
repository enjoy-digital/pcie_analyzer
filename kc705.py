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

from liteiclink.transceiver.gtx_7series import GTXChannelPLL, GTX

# IOs ----------------------------------------------------------------------------------------------

_io = [
    ("clk200", 0,
        Subsignal("p", Pins("AD12"), IOStandard("LVDS")),
        Subsignal("n", Pins("AD11"), IOStandard("LVDS"))
    ),

    ("cpu_reset", 0, Pins("AB7"), IOStandard("LVCMOS15")),

    ("user_led", 0, Pins("AB8"), IOStandard("LVCMOS15")),
    ("user_led", 1, Pins("AA8"), IOStandard("LVCMOS15")),
    ("user_led", 2, Pins("AC9"), IOStandard("LVCMOS15")),
    ("user_led", 3, Pins("AB9"), IOStandard("LVCMOS15")),
    ("user_led", 4, Pins("AE26"), IOStandard("LVCMOS25")),
    ("user_led", 5, Pins("G19"), IOStandard("LVCMOS25")),
    ("user_led", 6, Pins("E18"), IOStandard("LVCMOS25")),
    ("user_led", 7, Pins("F16"), IOStandard("LVCMOS25")),

    ("pcie_refclk", 0,
        Subsignal("p", Pins("U8")),
        Subsignal("n", Pins("U7"))
    ),

    ("pcie_tx", 0,
        Subsignal("p", Pins("L4")),
        Subsignal("n", Pins("L3"))
    ),
    ("pcie_rx", 0,
        Subsignal("p", Pins("M6")),
        Subsignal("n", Pins("M5"))
    ),

    ("pcie_tx", 1,
        Subsignal("p", Pins("M2")),
        Subsignal("n", Pins("M1"))
    ),
    ("pcie_rx", 1,
        Subsignal("p", Pins("P6")),
        Subsignal("n", Pins("P5"))
    ),
]


# Platform -----------------------------------------------------------------------------------------

class Platform(XilinxPlatform):
    def __init__(self):
        XilinxPlatform.__init__(self, "xc7k325t-ffg900-2", _io, toolchain="vivado")

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


class GTXTestSoC(SoCMini):
    def __init__(self, platform, connector="pcie", linerate=2.5e9, use_pcie_refclk=True, with_loopback=True):
        assert connector in ["pcie"]
        sys_clk_freq = int(100e6)

        # SoCMini ----------------------------------------------------------------------------------
        SoCMini.__init__(self, platform, sys_clk_freq)

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq)
        platform.add_period_constraint(self.crg.cd_sys.clk, 1e9/100e6)

        # GTX RefClk -------------------------------------------------------------------------------
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

        # GTX PLL ----------------------------------------------------------------------------------
        qpll = GTXChannelPLL(refclk, refclk_freq, linerate)
        print(qpll)
        self.submodules += qpll

        for i in range(2):
            # GTX --------------------------------------------------------------------------------------
            tx_pads = platform.request(connector + "_tx", i)
            rx_pads = platform.request(connector + "_rx", i)
            gtx = GTX(qpll, tx_pads, rx_pads, sys_clk_freq,
                data_width       = 20,
                clock_aligner    = False,
                tx_buffer_enable = True,
                rx_buffer_enable = True)
            setattr(self.submodules, "gtx"+str(i), gtx)
            if with_loopback:
                self.comb += gtx.loopback.eq(0b010) # Near-End PMA Loopback
            platform.add_period_constraint(gtx.cd_tx.clk, 1e9/gtx.tx_clk_freq)
            platform.add_period_constraint(gtx.cd_rx.clk, 1e9/gtx.rx_clk_freq)
            self.platform.add_false_path_constraints(
                self.crg.cd_sys.clk,
                gtx.cd_tx.clk,
                gtx.cd_rx.clk)

            # Test -------------------------------------------------------------------------------------
            counter = Signal(32)
            sync_tx = getattr(self.sync, "gtx{}_tx".format(i))
            sync_tx += counter.eq(counter + 1)

            # K28.5 and slow counter --> TX
            self.comb += [
                gtx.encoder.k[0].eq(1),
                gtx.encoder.d[0].eq((5 << 5) | 28),
                gtx.encoder.k[1].eq(0),
                gtx.encoder.d[1].eq(counter[26:]),
            ]

           # RX (slow counter) --> Leds
            for j in range(2):
                self.comb += platform.request("user_led", 2*i+j).eq(gtx.decoders[1].d[i])

# Load ---------------------------------------------------------------------------------------------

def load():
    from litex.build.xilinx import VivadoProgrammer
    prog = VivadoProgrammer()
    prog.load_bitstream("build/gateware/kc705.bit")
    exit()

# Build --------------------------------------------------------------------------------------------

def main():
    if "load" in sys.argv[1:]:
        load()
    platform = Platform()
    soc     = GTXTestSoC(platform)
    builder = Builder(soc, output_dir="build")
    builder.build(build_name="kc705")

if __name__ == "__main__":
    main()
