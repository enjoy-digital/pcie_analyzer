#!/usr/bin/env python3

# This file is Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

import sys
import argparse

from migen import *

from litex.build import tools

from litex.boards.platforms import netv2

from litex.soc.interconnect.csr import *
from litex.soc.cores.clock import *
from litex.soc.integration.soc_sdram import *
from litex.soc.integration.builder import *

from litedram.modules import K4B2G1646F
from litedram.phy import s7ddrphy

from liteeth.phy.rmii import LiteEthPHYRMII
from liteeth.core import LiteEthUDPIPCore
from liteeth.frontend.etherbone import LiteEthEtherbone

# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq):
        self.clock_domains.cd_sys       = ClockDomain()
        self.clock_domains.cd_sys4x     = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys4x_dqs = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200    = ClockDomain()
        self.clock_domains.cd_clk100    = ClockDomain()
        self.clock_domains.cd_eth       = ClockDomain()

        # # #

        clk50 = platform.request("clk50")
        platform.add_period_constraint(clk50, 1e9/50e6)

        self.submodules.pll = pll = S7PLL(speedgrade=-1)
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_sys,       sys_clk_freq)
        pll.create_clkout(self.cd_sys4x,     4*sys_clk_freq)
        pll.create_clkout(self.cd_sys4x_dqs, 4*sys_clk_freq, phase=90)
        pll.create_clkout(self.cd_clk200,    200e6)
        pll.create_clkout(self.cd_clk100,    100e6)
        pll.create_clkout(self.cd_eth,       50e6)

        self.submodules.idelayctrl = S7IDELAYCTRL(self.cd_clk200)

# PCIe Analyzer ------------------------------------------------------------------------------------

class PCIeAnalyzer(SoCSDRAM):
    def __init__(self, platform,
        with_cpu        = True,
        with_sdram      = True,
        with_etherbone  = True):
        sys_clk_freq = int(100e6)

        # SoCSDRAM ---------------------------------------------------------------------------------
        SoCSDRAM.__init__(self, platform, sys_clk_freq,
            cpu_type                 = "vexriscv" if with_cpu else None,
            csr_data_width           = 32,
            with_uart                = with_cpu,
            uart_name                = "crossover",
            integrated_rom_size      = 0x8000 if with_cpu else 0x0000,
            integrated_main_ram_size = 0x1000 if not with_sdram else 0x0000,
            ident                    = "PCIe Analyzer LiteX SoC",
            ident_version            = True)

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq)

        # DDR3 SDRAM -------------------------------------------------------------------------------
        if not self.integrated_main_ram_size:
            self.submodules.ddrphy = s7ddrphy.A7DDRPHY(platform.request("ddram"),
                memtype      = "DDR3",
                nphases      = 4,
                sys_clk_freq = sys_clk_freq)
            self.add_csr("ddrphy")
            sdram_module = K4B2G1646F(sys_clk_freq, "1:4")
            self.register_sdram(self.ddrphy,
                geom_settings   = sdram_module.geom_settings,
                timing_settings = sdram_module.timing_settings)

        # Etherbone --------------------------------------------------------------------------------
        if with_etherbone:
            # ethphy
            self.submodules.ethphy = LiteEthPHYRMII(
                clock_pads = self.platform.request("eth_clocks"),
                pads       = self.platform.request("eth"))
            self.add_csr("ethphy")
            # ethcore
            self.submodules.ethcore = LiteEthUDPIPCore(
                phy         = self.ethphy,
                mac_address = 0x10e2d5000000,
                ip_address  = "192.168.1.50",
                clk_freq    = self.clk_freq)
            # etherbone
            self.submodules.etherbone = LiteEthEtherbone(self.ethcore.udp, 1234)
            self.add_wb_master(self.etherbone.wishbone.bus)
            # timing constraints
            self.platform.add_period_constraint(self.ethphy.crg.cd_eth_rx.clk, 1e9/50e6)
            self.platform.add_period_constraint(self.ethphy.crg.cd_eth_tx.clk, 1e9/50e6)
            self.platform.add_false_path_constraints(
                self.crg.cd_sys.clk,
                self.ethphy.crg.cd_eth_rx.clk,
                self.ethphy.crg.cd_eth_tx.clk)

# Build --------------------------------------------------------------------------------------------

def main():
    with open("README.md") as f:
        description = [str(f.readline()) for i in range(1, 9)]
    parser = argparse.ArgumentParser(description="".join(description[1:]), formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--build", action="store_true", help="Build bitstream")
    parser.add_argument("--load",  action="store_true", help="Load bitstream")
    parser.add_argument("--flash", action="store_true", help="Flash bitstream")
    args = parser.parse_args()

    if args.load:
        from litex.build.openocd import OpenOCD
        prog = OpenOCD("openocd/openocd.cfg")
        prog.load_bitstream("build/gateware/top.bit")
        exit()

    if args.flash:
        from litex.build.openocd import OpenOCD
        prog = OpenOCD("openocd/openocd.cfg", flash_proxy_basename="openocd/bscan_spi_xc7a35t.bit")
        prog.set_flash_proxy_dir(".")
        prog.flash(0, "build/gateware/top.bin")
        exit()

    platform = netv2.Platform()
    soc      = PCIeAnalyzer(platform)
    builder  = Builder(soc, output_dir="build", csr_csv="test/csr.csv")
    builder.build(run=args.build)

if __name__ == "__main__":
    main()
