from amaranth.build import *

from .ice40 import *


__all__ = ["GlasgowRevC0Platform", "GlasgowRevC123Platform"]


class _GlasgowRevCPlatform(GlasgowICE40Platform):
    device      = "iCE40HX8K"
    package     = "BG121"
    default_clk = "clk_if"
    resources   = [
        Resource("clk_fx", 0, Pins("L5", dir="i"),
                 Clock(48e6), Attrs(GLOBAL="1", IO_STANDARD="SB_LVCMOS")),
        Resource("clk_if", 0, Pins("K6", dir="i"),
                 Clock(48e6), Attrs(GLOBAL="1", IO_STANDARD="SB_LVCMOS")),

        Resource("fx2", 0,
            Subsignal("sloe",    Pins("L3", dir="o")),
            Subsignal("slrd",    Pins("J5", dir="o")),
            Subsignal("slwr",    Pins("J4", dir="o")),
            Subsignal("pktend",  Pins("L1", dir="o")),
            Subsignal("fifoadr", Pins("K3 L2", dir="o")),
            Subsignal("flag",    Pins("L7 K5 L4 J3", dir="i")),
            Subsignal("fd",      Pins("H7 J7 J9 K10 L10 K9 L8 K7", dir="io")),
            Attrs(IO_STANDARD="SB_LVCMOS")
        ),

        Resource("i2c", 0,
            Subsignal("scl", Pins("H9", dir="io")),
            Subsignal("sda", Pins("J8", dir="io")),
            Attrs(IO_STANDARD="SB_LVCMOS")
        ),

        Resource("alert", 0, PinsN("K4", dir="oe"), Attrs(IO_STANDARD="SB_LVCMOS")),

        Resource("led", 0, Pins("G9", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led", 1, Pins("G8", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led", 2, Pins("E9", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led", 3, Pins("D9", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led", 4, Pins("E8", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),

        Resource("port_a", 0,
                 Subsignal("io", Pins("A1"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("C7", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_a", 1,
                 Subsignal("io", Pins("A2"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("C8", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_a", 2,
                 Subsignal("io", Pins("B3"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("D7", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_a", 3,
                 Subsignal("io", Pins("A3"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("A7", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_a", 4,
                 Subsignal("io", Pins("B6"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("B8", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_a", 5,
                 Subsignal("io", Pins("A4"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("A8", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_a", 6,
                 Subsignal("io", Pins("B7"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("B9", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_a", 7,
                 Subsignal("io", Pins("A5"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("A9", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),

        Resource("port_b", 0,
                 Subsignal("io", Pins("B11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("F9",  dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_b", 1,
                 Subsignal("io", Pins("C11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("G11", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_b", 2,
                 Subsignal("io", Pins("D10"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("G10", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_b", 3,
                 Subsignal("io", Pins("D11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("H11", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_b", 4,
                 Subsignal("io", Pins("E10"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("H10", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_b", 5,
                 Subsignal("io", Pins("E11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("J11", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_b", 6,
                 Subsignal("io", Pins("F11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("J10", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("port_b", 7,
                 Subsignal("io", Pins("F10"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("K11", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),

        Resource("aux", 0, Pins("A10"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("aux", 1, Pins("C9"),  Attrs(IO_STANDARD="SB_LVCMOS")),

        # On revC, these balls are shared with B6 and B7, respectively.
        # Since the default pin state is a weak pullup, we need to tristate them explicitly.
        Resource("unused", 0, Pins("A6 B5", dir="io"), Attrs(IO_STANDARD="SB_LVCMOS")),
    ]
    connectors  = [
        #                     1  2  3  4  5  6  7  8  9  10 11 12 13 14 15 16 17 18 19 20 21 22
        #                     23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44
        Connector("lvds", 0, "-  -  K1 -  J1 -  -  K2 H1 J2 H2 -  -  H3 G1 G3 G2 -  -  F3 F1 F4 "
                             "F2 -  -  E3 E1 E2 D1 -  -  D2 C1 D3 C2 -  -  C3 B1 C4 B2 -  -  -  "),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._init_glasgow_pins(
            ("A", "port_a", range(8)),
            ("B", "port_b", range(8)),
            ("S", "port_s", range(1)),
        )


class GlasgowRevC0Platform(_GlasgowRevCPlatform):
    resources = _GlasgowRevCPlatform.resources + [
        Resource("port_s", 0,
                 Subsignal("io", Pins("A11")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
    ]


class GlasgowRevC123Platform(_GlasgowRevCPlatform):
    resources = _GlasgowRevCPlatform.resources + [
        Resource("port_s", 0,
                 Subsignal("io", Pins("A11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("B4", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
    ]
