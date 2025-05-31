import logging
import asyncio
import struct
import array
import time
import statistics
import enum

from amaranth import *
from amaranth.lib import wiring, stream
from amaranth.lib.wiring import In, Out

from glasgow.gateware.lfsr import LinearFeedbackShiftRegister
from glasgow.applet import GlasgowAppletV2


RATE_WIDTH_TODO = 10


class Mode(enum.Enum):
    SOURCE   = 1
    SINK     = 2
    LOOPBACK = 3


class BenchmarkComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)
    mode:     In(Mode)
    rate_en:  In(1)
    rate:     In(RATE_WIDTH_TODO)
    stall:    Out(1)
    error:    Out(1)
    count:    Out(32)

    def __init__(self):
        self.lfsr = LinearFeedbackShiftRegister(degree=16, taps=(16, 15, 13, 4))

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        lfsr_en   = Signal()
        lfsr_word = Signal(8)
        m.submodules.lfsr = lfsr = EnableInserter(lfsr_en)(self.lfsr)
        m.d.comb += lfsr_word.eq(self.lfsr.value.word_select(self.count & 1, width=8))

        rate_count = Signal(self.rate.shape())

        act = Signal()
        with m.If(self.error):
            m.d.sync += act.eq(0)
        with m.Elif(self.rate_en):
            res = rate_count + self.rate + 1
            m.d.sync += rate_count.eq(res)
            with m.If(res[len(rate_count)]):
                with m.If(act):
                    self.error.eq(1)
                    self.stall.eq(1)
                with m.Else():
                    m.d.sync += act.eq(1)
        with m.Else():
            m.d.sync += act.eq(1)

        with m.FSM():
            with m.State("MODE"):
                m.d.sync += self.count.eq(0)
                with m.Switch(self.mode):
                    with m.Case(Mode.SOURCE):
                        m.next = "SOURCE"
                    with m.Case(Mode.SINK):
                        m.next = "SINK"
                    with m.Case(Mode.LOOPBACK):
                        m.next = "LOOPBACK"

            with m.State("SOURCE"):
                with m.If(act):
                    m.d.comb += [
                        self.o_stream.payload.eq(lfsr_word),
                        self.o_stream.valid.eq(1),
                    ]
                    with m.If(self.o_stream.ready):
                        m.d.comb += lfsr_en.eq(self.count & 1)
                        m.d.sync += self.count.eq(self.count + 1)
                        with m.If(self.rate_en):
                            m.d.sync += act.eq(0)
                with m.Elif(self.rate_en & self.error):
                    # Source dummy data to end pending read
                    m.d.comb += [
                        self.o_stream.valid.eq(1),
                        self.o_stream.payload.eq(0)
                    ]

            with m.State("SINK"):
                with m.If(act):
                    with m.If(self.i_stream.valid):
                        with m.If(self.i_stream.payload != lfsr_word):
                            m.d.sync += self.error.eq(1)
                        m.d.comb += [
                            self.i_stream.ready.eq(1),
                            lfsr_en.eq(self.count & 1),
                        ]
                        m.d.sync += self.count.eq(self.count + 1),
                        with m.If(self.rate_en):
                            m.d.sync += act.eq(0)
                    with m.Elif(self.rate_en & (self.count > 0)):
                        m.d.sync += [
                            self.error.eq(1),
                            self.stall.eq(1)
                        ]
                with m.Elif(self.rate_en & self.error):
                    # Sink data to end pending flush
                    m.d.comb += self.i_stream.ready.eq(1)

            with m.State("LOOPBACK"):
                with m.If(act):
                    m.d.comb += [
                        self.o_stream.payload.eq(self.i_stream.payload),
                        self.o_stream.valid.eq(self.i_stream.valid),
                        self.i_stream.ready.eq(self.o_stream.ready),
                    ]
                    with m.If(self.o_stream.ready & self.o_stream.valid):
                        with m.If(self.rate_en):
                            m.d.sync += act.eq(0)
                        m.d.sync += self.count.eq(self.count + 1)
                    with m.Elif(self.rate_en & (self.count > 0)):
                        m.d.sync += [
                            self.error.eq(1),
                            self.stall.eq(1)
                        ]
                    with m.Else():
                        m.d.comb += self.o_flush.eq(1)
                with m.Elif(self.rate_en & self.error):
                    # Sink/source data to end pending flush/read
                    m.d.comb += [
                        self.i_stream.ready.eq(1),
                        self.o_stream.valid.eq(1),
                        self.o_stream.payload.eq(0)
                    ]

        return m


class BenchmarkApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "evaluate communication performance"
    description = """
    Evaluate performance of the host communication link.

    Benchmark modes:

    * source: device emits an endless stream of data via one FIFO, host validates
      (simulates a logic analyzer subtarget)
    * sink: host emits an endless stream of data via one FIFO, device validates
      (simulates an I2S protocol subtarget)
    * loopback: host emits an endless stream of data via one FIFOs, device mirrors it all back,
      host validates (simulates an SPI protocol subtarget)
    * latency: host sends one packet, device sends it back, time until the packet is received back
      on the host is measured (simulates cases where a transaction with the DUT relies on feedback
      from the host; also useful for comparing different usb stacks or usb data paths like hubs or
      network bridges)
    """

    __all_modes = ["source", "sink", "loopback", "latency"]

    @classmethod
    def add_build_arguments(cls, parser, access):
        pass

    def build(self, args):
        with self.assembly.add_applet(self):
            component = self.assembly.add_submodule(BenchmarkComponent())
            self._pipe = self.assembly.add_inout_pipe(
                component.o_stream, component.i_stream, in_flush=component.o_flush,
                out_buffer_size=10) # TODO out_buffer_size doesn't act like expected?
            self._mode    = self.assembly.add_rw_register(component.mode)
            self._rate_en = self.assembly.add_rw_register(component.rate_en)
            self._rate    = self.assembly.add_rw_register(component.rate)
            self._error   = self.assembly.add_ro_register(component.error)
            self._count   = self.assembly.add_ro_register(component.count)

        sequence = array.array("H")
        sequence.extend(component.lfsr.generate())
        if struct.pack("H", 0x1234) != struct.pack("<H", 0x1234):
            sequence.byteswap()
        self._sequence = sequence.tobytes()

    @classmethod
    def add_run_arguments(cls, parser):
        length_group = parser.add_mutually_exclusive_group()

        length_group.add_argument(
            "-c", "--count", metavar="COUNT", type=int, default=1 << 23,
            help="transfer COUNT bytes (default: %(default)s)")
        
        length_group.add_argument(
            "-d", "--duration", metavar="DURATION", type=float,
            help="transfer for DURATION")
        
        length_group.add_argument(
            "--until-error", action="store_true",
            help="run mode(s) until an error occurs (or CTRL-C)")

        parser.add_argument(
            dest="modes", metavar="MODE", type=str, nargs="*", choices=[[]] + cls.__all_modes,
            help="run benchmark mode MODE (default: {})".format(" ".join(cls.__all_modes)))

        rate_group = parser.add_mutually_exclusive_group()

        rate_group.add_argument(
            "--rate", dest="rate_mibps", metavar="RATE", type=float,
            help="set device to source/sink data at constant RATE MiB/s and report FIFO over/underflows")

        # TODO rate-search doesn't make sense for latency test, how to handle for run all?
        rate_group.add_argument(
            "--rate-search", action="store_true",
            help="search for the fastest constant rate that data can be sourced/sunk without a FIFO over/underflow")
    
    async def source_io(self, golden, end_length=None, end_duration=None):
        length = 0
        begin = time.time()
        while True:
            actual = await self._pipe.recv(len(golden))
            duration = time.time() - begin
            length += len(golden)
            error = (actual != golden)
            if error:
                break
            elif end_length is not None and end_length <= length:
                break
            elif end_duration is not None and end_duration <= duration:
                break
        return (error, length, duration)
    
    async def sink_io(self, golden, end_length=None, end_duration=None, monitor_fut=None):
        length = 0
        begin = time.time()
        while True:
            await self._pipe.send(golden)
            duration = time.time() - begin
            length += len(golden)
            if monitor_fut is not None and monitor_fut.done():
                # TODO what goes here?
                break
            elif end_length is not None and end_length <= length:
                await self._pipe.flush()
                duration = time.time() - begin
                break
            elif end_duration is not None and end_duration <= duration:
                length = await self._count
                duration = time.time() - begin
                break
        return (None, length, duration)

    async def run(self, args):
        end_length = None
        end_duration = None
        if args.duration is not None:
            golden = self._sequence
            # TODO if duration * rate < len(_sequence)
            end_duration = args.duration
        elif args.until_error:
            golden = self._sequence
        else:
            golden = bytearray()
            while len(golden) < args.count:
                golden += self._sequence[:args.count - len(golden)]
            end_length = args.count

        # These requests are essentially free, as the data and control requests are independent,
        # both on the FX2 and on the USB bus.
        # TODO monitor back to counter + make async error thing for sink
        async def monitor():
            while True:
                await asyncio.sleep(0.1)
                if await bool(self._error):
                    return
                count = await self._count
                if args.duration is not None:
                    self.logger.debug("transferred %#x", count)
                else:
                    self.logger.debug("transferred %#x/%#x", count, args.count)

        for mode in args.modes or self.__all_modes:
            if args.duration is not None:
                length_val = args.duration
                unit_str = "s"
            else:
                length_val = len(golden) / (1 << 20)
                unit_str = "MiB"
            self.logger.info("running benchmark mode %s for %.3f %s",
                             mode, length_val, unit_str)

            if mode in ("source", "sink", "loopback"):
                if args.rate_mibps is not None:
                    await self._rate.set(self._mibps_to_rate(args.rate_mibps))
                    await self._rate_en.set(1)
                await self._mode.set(Mode[mode.upper()].value)
                await self._pipe.reset()
                #print("reset!")
                asdf = time.time()
                monitor_fut = asyncio.ensure_future(monitor())

                if mode == "source":
                    #print("asdf:", time.time() - asdf)
                    error, length, duration = await self.source_io(golden, end_length, end_duration)
                    count = 0 # TODO
                    count = await self._count
                    #print("ovf: ", await self._overflow)

                # TODO "overflowing after finish (actually good)"
                if mode == "sink":
                    error, length, duration = await self.sink_io(golden, end_length, end_duration, monitor_fut)
                    # TODO error/count
                    error = bool(await self._error)
                    count = await self._count

                # TODO 2x rate??
                if mode == "loopback":
                    asdf_TODO = await asyncio.gather(
                        self.source_io(golden, end_length, end_duration),
                        self.sink_io(golden, end_length, end_duration, monitor_fut)
                    )
                    error, length, duration = asdf_TODO[1]
                    length *= 2

                    count = None

                monitor_fut.cancel()

            if mode == "latency":
                packetmax = golden[:512]
                count = 0
                error = False
                roundtriptime = []

                await self._rate_en.set(0)
                await self._mode.set(Mode.LOOPBACK.value)
                await self._pipe.reset()
                monitor_fut = asyncio.ensure_future(monitor())

                latency_begin = time.time()
                while True:
                    begin = time.perf_counter()
                    await self._pipe.send(packetmax)
                    await self._pipe.flush()
                    actual = await self._pipe.recv(len(packetmax))
                    end = time.perf_counter()

                    # calculate roundtrip time in µs
                    roundtriptime.append((end - begin) * 1000000)
                    if actual != packetmax:
                        error = True
                        break
                    count += len(packetmax) * 2

                    if end_duration is not None:
                        if end_duration <= time.time() - latency_begin:
                            break
                    elif count < args.count:
                        break

                monitor_fut.cancel()

            if error:
                if count is None:
                    self.logger.error("mode %s failed!", mode)
                else:
                    self.logger.error("mode %s failed at %#x!", mode, count)
            else:
                if mode == "latency":
                    self.logger.info("mode %s: mean: %.2f µs stddev: %.2f µs worst: %.2f µs",
                                 mode,
                                 statistics.mean(roundtriptime),
                                 statistics.pstdev(roundtriptime),
                                 max(roundtriptime))
                else:
                    self.logger.info("mode %s: %.2f MiB/s (%.2f Mb/s)",
                                 mode,
                                 (length / (duration)) / (1 << 20),
                                 (length / (duration)) / (1 << 17))

    def _mibps_to_rate(self, mibps):
        ret = round(mibps*(1<<RATE_WIDTH_TODO)/(48)) - 1
        ret = min(max(ret, 0), (1<<RATE_WIDTH_TODO)-1)
        return ret

    @classmethod
    def tests(cls):
        from . import test
        return test.BenchmarkAppletTestCase
