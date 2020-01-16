#!/usr/bin/env python3

# This file is Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

import sys

from migen import *

from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform

from litex.soc.cores.clock import *
from litex.soc.integration.soc_sdram import *
from litex.soc.integration.builder import *

from litedram.modules import MT8JTF12864
from litedram.phy import s7ddrphy

from liteeth.phy import LiteEthPHY
from liteeth.core import LiteEthUDPIPCore
from liteeth.frontend.etherbone import LiteEthEtherbone

from liteiclink.transceiver.gtx_7series import GTXQuadPLL, GTX

from pcie_analyzer.record import Recorder

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

    ("eth_clocks", 0,
        Subsignal("tx", Pins("M28")),
        Subsignal("gtx", Pins("K30")),
        Subsignal("rx", Pins("U27")),
        IOStandard("LVCMOS25")
    ),
    ("eth", 0,
        Subsignal("rst_n", Pins("L20")),
        Subsignal("int_n", Pins("N30")),
        Subsignal("mdio", Pins("J21")),
        Subsignal("mdc", Pins("R23")),
        Subsignal("rx_dv", Pins("R28")),
        Subsignal("rx_er", Pins("V26")),
        Subsignal("rx_data", Pins("U30 U25 T25 U28 R19 T27 T26 T28")),
        Subsignal("tx_en", Pins("M27")),
        Subsignal("tx_er", Pins("N29")),
        Subsignal("tx_data", Pins("N27 N25 M29 L28 J26 K26 L30 J28")),
        Subsignal("col", Pins("W19")),
        Subsignal("crs", Pins("R30")),
        IOStandard("LVCMOS25")
    ),

    ("ddram", 0,
        Subsignal("a", Pins(
            "AH12 AG13 AG12 AF12 AJ12 AJ13 AJ14 AH14",
            "AK13 AK14 AF13 AE13 AJ11 AH11 AK10 AK11"),
            IOStandard("SSTL15")),
        Subsignal("ba", Pins("AH9 AG9 AK9"), IOStandard("SSTL15")),
        Subsignal("ras_n", Pins("AD9"), IOStandard("SSTL15")),
        Subsignal("cas_n", Pins("AC11"), IOStandard("SSTL15")),
        Subsignal("we_n", Pins("AE9"), IOStandard("SSTL15")),
        Subsignal("cs_n", Pins("AC12"), IOStandard("SSTL15")),
        Subsignal("dm", Pins("Y16 AB17 AF17 AE16"),
            IOStandard("SSTL15")),
        Subsignal("dq", Pins(
            "AA15 AA16 AC14 AD14 AA17 AB15 AE15 Y15",
            "AB19 AD16 AC19 AD17 AA18 AB18 AE18 AD18",
            "AG19 AK19 AG18 AF18 AH19 AJ19 AE19 AD19",
            "AK16 AJ17 AG15 AF15 AH17 AG14 AH15 AK15"),
            IOStandard("SSTL15_T_DCI")),
        Subsignal("dqs_p", Pins("AC16 Y19 AJ18 AH16"),
            IOStandard("DIFF_SSTL15")),
        Subsignal("dqs_n", Pins("AC15 Y18 AK18 AJ16"),
            IOStandard("DIFF_SSTL15")),
        Subsignal("clk_p", Pins("AG10"), IOStandard("DIFF_SSTL15")),
        Subsignal("clk_n", Pins("AH10"), IOStandard("DIFF_SSTL15")),
        Subsignal("cke", Pins("AF10"), IOStandard("SSTL15")),
        Subsignal("odt", Pins("AD8"), IOStandard("SSTL15")),
        Subsignal("reset_n", Pins("AK3"), IOStandard("LVCMOS15")),
        Misc("SLEW=FAST"),
        Misc("VCCAUX_IO=HIGH")
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
        self.clock_domains.cd_sys4x  = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()

        # # #

        clk200 = platform.request("clk200")
        rst    = platform.request("cpu_reset")
        platform.add_period_constraint(clk200.p, 1e9/200e6)

        self.submodules.pll = pll = S7MMCM(speedgrade=-2)
        self.comb += pll.reset.eq(rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys,    sys_clk_freq)
        pll.create_clkout(self.cd_sys4x,  4*sys_clk_freq)
        pll.create_clkout(self.cd_clk200, 200e6)

        self.submodules.idelayctrl = S7IDELAYCTRL(self.cd_clk200)

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
        self.submodules.ddrphy = s7ddrphy.K7DDRPHY(platform.request("ddram"),
            memtype      = "DDR3",
            nphases      = 4,
            sys_clk_freq = sys_clk_freq)
        self.add_csr("ddrphy")
        sdram_module = MT8JTF12864(sys_clk_freq, "1:4")
        self.register_sdram(self.ddrphy,
            geom_settings   = sdram_module.geom_settings,
            timing_settings = sdram_module.timing_settings)

        # Ethernet ---------------------------------------------------------------------------------
        # phy
        self.submodules.eth_phy = LiteEthPHY(
            clock_pads = platform.request("eth_clocks"),
            pads       = platform.request("eth"),
            clk_freq   = sys_clk_freq)
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

        # GTX RefClk -------------------------------------------------------------------------------
        refclk      = Signal()
        refclk_freq = 100e6
        refclk_pads = platform.request("pcie_refclk")
        self.specials += Instance("IBUFDS_GTE2",
            i_CEB   = 0,
            i_I     = refclk_pads.p,
            i_IB    = refclk_pads.n,
            o_O     = refclk)

        # GTX PLL ----------------------------------------------------------------------------------
        qpll = GTXQuadPLL(refclk, refclk_freq, linerate)
        print(qpll)
        self.submodules += qpll

        # GTXs -------------------------------------------------------------------------------------
        for i in range(2):
            tx_pads = platform.request(connector + "_tx", i)
            rx_pads = platform.request(connector + "_rx", i)
            gtx = GTX(qpll, tx_pads, rx_pads, sys_clk_freq,
                data_width       = 20,
                clock_aligner    = False,
                tx_buffer_enable = True,
                rx_buffer_enable = True)
            gtx.add_stream_endpoints()
            setattr(self.submodules, "gtx"+str(i), gtx)
            platform.add_period_constraint(gtx.cd_tx.clk, 1e9/gtx.tx_clk_freq)
            platform.add_period_constraint(gtx.cd_rx.clk, 1e9/gtx.rx_clk_freq)
            self.platform.add_false_path_constraints(
                self.crg.cd_sys.clk,
                gtx.cd_tx.clk,
                gtx.cd_rx.clk)


        # Record -------------------------------------------------------------------------------------
        self.submodules.gtx0_recorder = Recorder(
            dram_port    = self.sdram.crossbar.get_port("write", 32),
            clock_domain = "gtx0_rx")
        self.add_csr("gtx0_recorder")
        self.submodules.gtx1_recorder = Recorder(
            dram_port    = self.sdram.crossbar.get_port("write", 32),
            clock_domain = "gtx1_rx")
        self.add_csr("gtx1_recorder")
        self.comb += [
            self.gtx0_recorder.sink.valid.eq(self.gtx0.source.valid),
            self.gtx0_recorder.sink.data.eq(self.gtx0.source.payload.raw_bits()),
            self.gtx1_recorder.sink.valid.eq(self.gtx1.source.valid),
            self.gtx1_recorder.sink.data.eq(self.gtx1.source.payload.raw_bits()),
        ]

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
    soc     = PCIeAnalyzer(platform)
    builder = Builder(soc, output_dir="build", csr_csv="tools/csr.csv")
    builder.build(build_name="kc705")

if __name__ == "__main__":
    main()
