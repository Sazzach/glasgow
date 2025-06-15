import logging
import asyncio
import struct
import array
import time
import statistics
import enum # TODO amaranth enum?
import itertools

from amaranth import *
from amaranth.lib import wiring, stream
from amaranth.lib.wiring import In, Out

from glasgow.gateware.lfsr import LinearFeedbackShiftRegister
from glasgow.abstract import AbstractAssembly
from glasgow.applet import GlasgowAppletV2


class Mode(enum.IntEnum):
    SOURCE   = 1
    SINK     = 2
    LOOPBACK = 3


class BenchmarkComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)
    mode:     In(Mode)
    rate_en:  In(1)
    rate:     In(10)
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
        #with m.If(self.error):
            #m.d.sync += act.eq(0)
        #with m.Elif(self.rate_en):
        with m.If(self.rate_en):
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


class BenchmarkInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly):
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._assembly = assembly

        component = assembly.add_submodule(BenchmarkComponent())
        self._pipe = assembly.add_inout_pipe(
            component.o_stream, component.i_stream, in_flush=component.o_flush,
            out_buffer_size=int(1e6)) # TODO out_buffer_size doesn't act like expected?
        self._mode    = assembly.add_rw_register(component.mode)
        self._rate_en = assembly.add_rw_register(component.rate_en)
        self._rate    = assembly.add_rw_register(component.rate)
        self._error   = assembly.add_ro_register(component.error)
        self._count   = assembly.add_ro_register(component.count)

        sequence = array.array("H")
        sequence.extend(component.lfsr.generate())
        if struct.pack("H", 0x1234) != struct.pack("<H", 0x1234):
            sequence.byteswap()
        self._sequence = sequence.tobytes()
    
    async def source(self, *, length=None, duration=None):
        golden = self._make_golden(length)
        await self._pipe.reset()
        await self._mode.set(Mode.SOURCE)
        return await self.source_io(golden, length, duration)
    
    async def sink(self, *, length=None, duration=None):
        golden = self._make_golden(length)
        await self._pipe.reset()
        await self._mode.set(Mode.SINK)
        return await self.sink_io(golden, length, duration)
    
    async def test(self):
        await self._mode.set(Mode.SOURCE)
        print(await self._pipe.send(self._make_golden(10)))
        print(await self._pipe.send(self._make_golden(10)))

    async def loopback(self, *, length=None, duration=None):
        golden = self._make_golden(length)
        await self._pipe.reset()
        await self._mode.set(Mode.LOOPBACK)
        result = await asyncio.gather(
            self.source_io(golden, length, duration),
            self.sink_io(golden, length, duration)
        )
        error, length, duration = result[1]
        length *= 2
        return error, length, duration

    async def latency(self, samples=None, duration=None):
        packetmax = self._make_golden(512)
        count = 0
        error = False
        roundtriptime = []

        await self._pipe.reset()
        await self._mode.set(Mode.LOOPBACK.value)
        #counter_fut = asyncio.ensure_future(counter())

        latency_begin = time.time()
        while True:
            if duration is not None:
                if time.time() - latency_begin >= duration:
                    break
            elif count >= samples:
                break

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
            count += 1
        return error, roundtriptime

    def _make_golden(self, length):
        golden = bytearray()
        while len(golden) < length:
            golden += self._sequence[:length - len(golden)]
        return golden

    # These requests are essentially free, as the data and control requests are independent,
    # both on the FX2 and on the USB bus.
    async def _counter():
        while True:
            await asyncio.sleep(0.1)
            count = await self._count
            if args.duration is not None:
                self.logger.debug("transferred %#x", count)
            else:
                self.logger.debug("transferred %#x/%#x", count, args.count)

    def _mibps_to_rate(self, mibps):
        rate_width = self._rate.shape.width
        mbps = mibps * (48 * (1 << 20)) / 48e6
        ret = round(mbps*(1<<rate_width)/48) - 1
        ret = min(max(ret, 0), (1<<rate_width)-1)
        return ret

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
    
    async def sink_io(self, golden, end_length=None, end_duration=None):
        async def error_monitor():
            return
            #while not bool(await self._error):
                #await asyncio.sleep(0.1)
        
        monitor_fut = asyncio.ensure_future(error_monitor())

        length = 0
        begin = time.time()
        while True:
            await self._pipe.send(golden)
            duration = time.time() - begin
            length += len(golden)
            if monitor_fut.done():
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
        
        monitor_fut.cancel()
        return (None, length, duration)


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
            self.benchmark_iface = BenchmarkInterface(self.logger, self.assembly)

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

        parser.add_argument(
            "--rate", dest="rate_mibps", metavar="RATE", type=float,
            help="set device to source/sink data at constant RATE MiB/s and report FIFO over/underflows")

    async def run(self, args):
        for mode in args.modes or self.__all_modes:
            if args.duration is not None:
                length_val = args.duration
                unit_str = "s"
            else:
                length_val = args.count / (1 << 20)
                unit_str = "MiB"
            self.logger.info("running benchmark mode %s for %.3f %s",
                             mode, length_val, unit_str)

            match mode:
                case "source":
                    error, length, duration = await self.benchmark_iface.source(
                        length=args.count, duration=args.duration
                    )
                case "sink":
                    error, length, duration = await self.benchmark_iface.sink(
                        length=args.count, duration=args.duration
                    )
                case "loopback":
                    error, length, duration = await self.benchmark_iface.loopback(
                        length=args.count, duration=args.duration
                    )
                case "latency":
                    error, roundtriptime = await self.benchmark_iface.latency(
                        samples=args.count // (512 * 2), duration=args.duration
                    )
                    length = len(roundtriptime) * (512 * 2)

            if error:
                self.logger.error("mode %s failed at %#x!", mode, length)
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

    @classmethod
    def tests(cls):
        from . import test
        return test.BenchmarkAppletTestCase
