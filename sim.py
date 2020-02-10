#!/usr/bin/env python3

# This file is Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

import argparse

from migen import *

from litex.build.generic_platform import *
from litex.build.sim import SimPlatform
from litex.build.sim.config import SimConfig

from litex.soc.integration.soc_sdram import *
from litex.soc.integration.builder import *
from litex.soc.cores import uart

from litedram.common import PhySettings
from litedram.modules import MT48LC16M16
from litedram.phy.model import SDRAMPHYModel
from litedram.frontend.dma import LiteDRAMDMAWriter

from liteeth.phy.model import LiteEthPHYModel
from liteeth.core import LiteEthUDPIPCore
from liteeth.frontend.etherbone import LiteEthEtherbone

# IOs ----------------------------------------------------------------------------------------------

_io = [
    ("sys_clk", 0, Pins(1)),
    ("sys_rst", 0, Pins(1)),
    ("eth_clocks", 0,
        Subsignal("tx", Pins(1)),
        Subsignal("rx", Pins(1)),
    ),
    ("eth", 0,
        Subsignal("source_valid", Pins(1)),
        Subsignal("source_ready", Pins(1)),
        Subsignal("source_data",  Pins(8)),

        Subsignal("sink_valid",   Pins(1)),
        Subsignal("sink_ready",   Pins(1)),
        Subsignal("sink_data",    Pins(8)),
    ),
]

# Platform -----------------------------------------------------------------------------------------

class Platform(SimPlatform):
    def __init__(self):
        SimPlatform.__init__(self, "SIM", _io)

# PCIeAnalyzer -------------------------------------------------------------------------------------

class PCIeAnalyzer(SoCSDRAM):
    def __init__(self, **kwargs):
        platform     = Platform()
        sys_clk_freq = int(1e6)

        # SoCSDRAM ---------------------------------------------------------------------------------
        SoCSDRAM.__init__(self, platform, sys_clk_freq,
            integrated_rom_size  = 0x8000,
            integrated_sram_size = 0x1000,
            uart_name            = "crossover",
            l2_size              = 0,
            csr_data_width       = 32,
            **kwargs
        )

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = CRG(platform.request("sys_clk"))

        # SDR SDRAM --------------------------------------------------------------------------------
        sdram_module = MT48LC16M16(100e6, "1:1") # use 100MHz timings
        phy_settings = PhySettings(
            memtype       = "SDR",
            databits      = 32,
            dfi_databits  = 16,
            nphases       = 1,
            rdphase       = 0,
            wrphase       = 0,
            rdcmdphase    = 0,
            wrcmdphase    = 0,
            cl            = 2,
            read_latency  = 4,
            write_latency = 0
        )
        self.submodules.sdrphy = SDRAMPHYModel(sdram_module, phy_settings)
        self.register_sdram(
            self.sdrphy,
            sdram_module.geom_settings,
            sdram_module.timing_settings)
        # Disable Memtest for simulation speedup
        self.add_constant("MEMTEST_BUS_SIZE",  0)
        self.add_constant("MEMTEST_ADDR_SIZE", 0)
        self.add_constant("MEMTEST_DATA_SIZE", 0)

        # Ethernet ---------------------------------------------------------------------------------
        # phy
        self.submodules.ethphy = LiteEthPHYModel(self.platform.request("eth"))
        self.add_csr("ethphy")
        # core
        ethcore = LiteEthUDPIPCore(self.ethphy,
            mac_address = 0x10e2d5000000,
            ip_address  = "192.168.1.50",
            clk_freq    = sys_clk_freq)
        self.submodules.ethcore = ethcore
        # etherbone
        self.submodules.etherbone = LiteEthEtherbone(self.ethcore.udp, 1234, mode="master")
        self.add_wb_master(self.etherbone.wishbone.bus)

        # Record -----------------------------------------------------------------------------------
        self.submodules.rx_dma_recorder = LiteDRAMDMAWriter(self.sdram.crossbar.get_port("write", 32))
        self.rx_dma_recorder.add_csr()
        self.add_csr("rx_dma_recorder")
        self.submodules.tx_dma_recorder = LiteDRAMDMAWriter(self.sdram.crossbar.get_port("write", 32))
        self.tx_dma_recorder.add_csr()
        self.add_csr("tx_dma_recorder")
        counter = Signal(32)
        self.sync += counter.eq(counter + 1)
        self.comb += [
            self.rx_dma_recorder.sink.valid.eq(1),
            self.rx_dma_recorder.sink.data.eq(counter),
            self.tx_dma_recorder.sink.valid.eq(1),
            self.tx_dma_recorder.sink.data.eq(counter),
        ]

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="PCIeAnalyzer LiteX SoC Simulation")
    builder_args(parser)
    soc_sdram_args(parser)
    parser.add_argument("--threads",     default=1,           help="Set number of threads (default=1)")
    parser.add_argument("--rom-init",    default=None,        help="rom_init file")
    parser.add_argument("--trace",       action="store_true", help="Enable VCD tracing")
    parser.add_argument("--trace-start", default=0,           help="Cycle to start VCD tracing")
    parser.add_argument("--trace-end",   default=-1,          help="Cycle to end VCD tracing")
    parser.add_argument("--opt-level",   default="O0",        help="Compilation optimization level")
    args = parser.parse_args()

    soc_kwargs     = {}
    builder_kwargs = builder_argdict(args)

    sim_config = SimConfig(default_clk="sys_clk")

    # Configuration --------------------------------------------------------------------------------
    if args.rom_init:
        soc_kwargs["integrated_rom_init"] = get_mem_data(args.rom_init, "little")
    sim_config.add_module("ethernet", "eth", args={"interface": "tap0", "ip": "192.168.1.100"})

    # Build  ---------------------------------------------------------------------------------------
    soc     = PCIeAnalyzer(**soc_kwargs)
    builder = Builder(soc, csr_csv="tools/csr.csv")
    vns = builder.build(threads=args.threads, sim_config=sim_config,
        opt_level   = args.opt_level,
        trace       = args.trace,
        trace_start = int(args.trace_start),
        trace_end   = int(args.trace_end)
    )

if __name__ == "__main__":
    main()
