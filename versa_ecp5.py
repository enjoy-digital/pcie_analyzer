#!/usr/bin/env python3

# This file is Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

import sys

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex.build.generic_platform import *

from litex.boards.platforms import versa_ecp5

from litex.soc.cores.clock import *
from litex.soc.integration.soc_sdram import *
from litex.soc.integration.builder import *

from litedram.modules import MT41K64M16
from litedram.phy import ECP5DDRPHY

from liteeth.phy.ecp5rgmii import LiteEthPHYRGMII
from liteeth.core import LiteEthUDPIPCore
from liteeth.frontend.etherbone import LiteEthEtherbone

# IOs ----------------------------------------------------------------------------------------------

_pcie_io = [
    # PCIe
    ("pcie_rx", 0,
        Subsignal("p", Pins("Y5")),
        Subsignal("n", Pins("Y6")),
    ),
    ("pcie_tx", 0,
        Subsignal("p", Pins("W4")),
        Subsignal("n", Pins("W5")),
    ),
]

# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq):
        self.clock_domains.cd_init    = ClockDomain()
        self.clock_domains.cd_por     = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys     = ClockDomain()
        self.clock_domains.cd_sys2x   = ClockDomain()
        self.clock_domains.cd_sys2x_i = ClockDomain(reset_less=True)

        # # #

        self.stop = Signal()

        # Clk / Rst
        clk100 = platform.request("clk100")
        rst_n  = platform.request("rst_n")
        platform.add_period_constraint(clk100, 1e9/100e6)

        # Power on reset
        por_count = Signal(16, reset=2**16-1)
        por_done  = Signal()
        self.comb += self.cd_por.clk.eq(ClockSignal())
        self.comb += por_done.eq(por_count == 0)
        self.sync.por += If(~por_done, por_count.eq(por_count - 1))

        # PLL
        self.submodules.pll = pll = ECP5PLL()
        pll.register_clkin(clk100, 100e6)
        pll.create_clkout(self.cd_sys2x_i, 2*sys_clk_freq)
        pll.create_clkout(self.cd_init, 25e6)
        self.specials += [
            Instance("ECLKSYNCB",
                i_ECLKI = self.cd_sys2x_i.clk,
                i_STOP  = self.stop,
                o_ECLKO = self.cd_sys2x.clk),
            Instance("CLKDIVF",
                p_DIV     = "2.0",
                i_ALIGNWD = 0,
                i_CLKI    = self.cd_sys2x.clk,
                i_RST     = self.cd_sys2x.rst,
                o_CDIVX   = self.cd_sys.clk),
            AsyncResetSynchronizer(self.cd_init, ~por_done | ~pll.locked | ~rst_n),
            AsyncResetSynchronizer(self.cd_sys, ~por_done | ~pll.locked | ~rst_n)
        ]
# PCIe Analyzer ------------------------------------------------------------------------------------

class PCIeAnalyzer(SoCSDRAM):
    def __init__(self, platform, connector="pcie", linerate=2.5e9):
        assert connector in ["pcie"]
        sys_clk_freq = int(125e6)

        # SoCSDRAM ----------------------------------------------------------------------------------
        SoCSDRAM.__init__(self, platform, sys_clk_freq,
            integrated_rom_size  = 0x8000,
            integrated_sram_size = 0x1000,
            uart_name            = "crossover",
            csr_data_width       = 32,
        )

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq)
        platform.add_period_constraint(self.crg.cd_sys.clk, 1e9/100e6)

        # DDR3 SDRAM -------------------------------------------------------------------------------
        if not self.integrated_main_ram_size:
            self.submodules.ddrphy = ECP5DDRPHY(
                platform.request("ddram"),
                sys_clk_freq=sys_clk_freq)
            self.add_csr("ddrphy")
            self.add_constant("ECP5DDRPHY", None)
            self.comb += self.crg.stop.eq(self.ddrphy.init.stop)
            sdram_module = MT41K64M16(sys_clk_freq, "1:2")
            self.register_sdram(self.ddrphy,
                geom_settings   = sdram_module.geom_settings,
                timing_settings = sdram_module.timing_settings)

        # Ethernet ---------------------------------------------------------------------------------
        # phy
        self.submodules.eth_phy = LiteEthPHYRGMII(
            clock_pads = platform.request("eth_clocks"),
            pads       = platform.request("eth"))
        self.add_csr("eth_phy")
        # core
        self.submodules.eth_core = LiteEthUDPIPCore(
            phy         = self.eth_phy,
            mac_address = 0x10e2d5000000,
            ip_address  = "192.168.1.50",
            clk_freq    = sys_clk_freq)
        # etherbone
        self.submodules.etherbone = LiteEthEtherbone(self.eth_core.udp, 1234)
        self.add_wb_master(self.etherbone.wishbone.bus)

        # timing constraints
        self.platform.add_period_constraint(self.eth_phy.crg.cd_eth_rx.clk, 1e9/125e6)
        self.platform.add_period_constraint(self.eth_phy.crg.cd_eth_tx.clk, 1e9/125e6)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            self.eth_phy.crg.cd_eth_rx.clk,
            self.eth_phy.crg.cd_eth_tx.clk)

# Load ---------------------------------------------------------------------------------------------

def load():
    import os
    f = open("ecp5-versa5g.cfg", "w")
    f.write(
"""
interface ftdi
ftdi_vid_pid 0x0403 0x6010
ftdi_channel 0
ftdi_layout_init 0xfff8 0xfffb
reset_config none
adapter_khz 25000
jtag newtap ecp5 tap -irlen 8 -expected-id 0x81112043
""")
    f.close()
    os.system("openocd -f ecp5-versa5g.cfg -c \"transport select jtag; init; svf build/gateware/versa_ecp5.svf; exit\"")
    exit()

# Build --------------------------------------------------------------------------------------------

def main():
    if "load" in sys.argv[1:]:
        load()
    platform = versa_ecp5.Platform(toolchain="trellis")
    platform.add_extension(_pcie_io)
    soc      = PCIeAnalyzer(platform)
    builder  = Builder(soc, output_dir="build", csr_csv="tools/csr.csv")
    builder.build(build_name="versa_ecp5", toolchain_path="/usr/local/diamond/3.10_x64/bin/lin64")

if __name__ == "__main__":
    main()
