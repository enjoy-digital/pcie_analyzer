#!/usr/bin/env python3

# This file is Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

import sys
import argparse

from migen import *

from litex.build import tools

from litex.build.generic_platform import *
from litex.boards.platforms import netv2

from litex.soc.interconnect.csr import *
from litex.soc.interconnect import stream
from litex.soc.cores.clock import *
from litex.soc.integration.soc_sdram import *
from litex.soc.integration.builder import *
from litex.soc.cores.freqmeter import FreqMeter

from litedram.modules import K4B2G1646F
from litedram.phy import s7ddrphy
from litedram.frontend.dma import LiteDRAMDMAWriter

from liteeth.phy.rmii import LiteEthPHYRMII
from liteeth.core import LiteEthUDPIPCore
from liteeth.frontend.etherbone import LiteEthEtherbone

from liteiclink.transceiver.gtp_7series import GTPQuadPLL, GTP

from pcie_analyzer.bist import GTPTXBIST, GTPRXBIST

# IOs ----------------------------------------------------------------------------------------------

_pcie_analyzer_io = [

    ("pcie_refclk", 0,
        Subsignal("p", Pins("F10")),
        Subsignal("n", Pins("E10"))
    ),

    ("pcie_tx", 0,
        Subsignal("p", Pins("D5")),
        Subsignal("n", Pins("C5"))
    ),
    ("pcie_rx", 0,
        Subsignal("p", Pins("D11")),
        Subsignal("n", Pins("C11"))
    ),

    ("pcie_tx", 1,
        Subsignal("p", Pins("B6")),
        Subsignal("n", Pins("A6"))
    ),
    ("pcie_rx", 1,
        Subsignal("p", Pins("B10")),
        Subsignal("n", Pins("A10"))
    ),
]

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
        with_cpu           = True,
        with_sdram         = True,
        with_etherbone     = True,
        with_gtp           = True, gtp_connector="pcie", gtp_refclk="pcie", gtp_linerate=5e9,
        with_gtp_bist      = True,
        with_gtp_freqmeter = True,
        with_record        = True):
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

        # GTP RefClk -------------------------------------------------------------------------------
        if with_gtp:
            assert gtp_refclk in ["pcie", "internal"]
            if gtp_refclk == "pcie":
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
                refclk_freq = 100e6
                self.comb += refclk.eq(ClockSignal("clk100"))
                platform.add_platform_command("set_property SEVERITY {{Warning}} [get_drc_checks REQP-49]")

        # GTP PLL ----------------------------------------------------------------------------------
        if with_gtp:
            qpll = GTPQuadPLL(refclk, refclk_freq, gtp_linerate)
            print(qpll)
            self.submodules += qpll

        # GTPs -------------------------------------------------------------------------------------
        if with_gtp:
            for i in range(2):
                tx_pads = platform.request(gtp_connector + "_tx", i)
                rx_pads = platform.request(gtp_connector + "_rx", i)
                gtp = GTP(qpll, tx_pads, rx_pads, sys_clk_freq,
                    data_width       = 20,
                    clock_aligner    = False,
                    tx_buffer_enable = True,
                    rx_buffer_enable = True)
                gtp.add_stream_endpoints()
                setattr(self.submodules, "gtp"+str(i), gtp)
                platform.add_period_constraint(gtp.cd_tx.clk, 1e9/gtp.tx_clk_freq)
                platform.add_period_constraint(gtp.cd_rx.clk, 1e9/gtp.rx_clk_freq)
                self.platform.add_false_path_constraints(
                    self.crg.cd_sys.clk,
                    gtp.cd_tx.clk,
                    gtp.cd_rx.clk)

        # GTPs FreqMeters --------------------------------------------------------------------------
        if with_gtp_freqmeter:
            self.submodules.gtp0_tx_freq = FreqMeter(ClockSignal("gtp0_tx"))
            self.submodules.gtp0_rx_freq = FreqMeter(ClockSignal("gtp0_rx"))
            self.submodules.gtp1_tx_freq = FreqMeter(ClockSignal("gtp1_tx"))
            self.submodules.gtp1_rx_freq = FreqMeter(ClockSignal("gtp1_rx"))
            self.add_csr("gtp0_tx_freq")
            self.add_csr("gtp0_rx_freq")
            self.add_csr("gtp1_tx_freq")
            self.add_csr("gtp1_rx_freq")

        # GTPs BIST --------------------------------------------------------------------------------
        if with_gtp_bist:
            self.submodules.gtp0_tx_bist = GTPTXBIST(self.gtp0, "gtp0_tx")
            self.submodules.gtp0_rx_bist = GTPRXBIST(self.gtp0, "gtp0_rx")
            self.submodules.gtp1_tx_bist = GTPTXBIST(self.gtp1, "gtp1_tx")
            self.submodules.gtp1_rx_bist = GTPRXBIST(self.gtp1, "gtp1_rx")
            self.add_csr("gtp0_tx_bist")
            self.add_csr("gtp0_rx_bist")
            self.add_csr("gtp1_tx_bist")
            self.add_csr("gtp1_rx_bist")

        # Record -----------------------------------------------------------------------------------
        # FIXME: use better data/ctrl packing (or separate recorders)
        if with_record:
            # Convert RX stream from 16-bit@250MHz to 64-bit@sys_clk
            rx_converter = stream.StrideConverter(
                [("data", 16), ("ctrl",  2)],
                [("data", 96), ("ctrl", 12)],
                reverse     = False)
            rx_converter = ClockDomainsRenamer("gtp0_rx")(rx_converter)
            self.submodules.rx_converter = rx_converter
            rx_cdc = stream.AsyncFIFO([("data", 96), ("ctrl", 12)], 8, buffered=True)
            rx_cdc = ClockDomainsRenamer({"write": "gtp0_rx", "read": "sys"})(rx_cdc)
            self.submodules.rx_cdc = rx_cdc
            # RX DMA Recorder
            self.submodules.rx_dma_recorder = LiteDRAMDMAWriter(self.sdram.crossbar.get_port("write", 128))
            self.rx_dma_recorder.add_csr()
            self.add_csr("rx_dma_recorder")
            self.comb += [
                gtp.source.connect(rx_converter.sink),
                rx_converter.source.connect(rx_cdc.sink),
                self.rx_dma_recorder.sink.valid.eq(rx_cdc.source.valid),
                self.rx_dma_recorder.sink.data[0:96].eq(rx_cdc.source.data),
                self.rx_dma_recorder.sink.data[96:108].eq(rx_cdc.source.ctrl),
            ]

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
    platform.add_extension(_pcie_analyzer_io)
    soc      = PCIeAnalyzer(platform)
    builder  = Builder(soc, output_dir="build", csr_csv="tools/csr.csv")
    builder.build(run=args.build)

if __name__ == "__main__":
    main()
