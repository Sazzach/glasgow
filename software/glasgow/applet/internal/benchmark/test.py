from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import BenchmarkApplet


class BenchmarkAppletTestCase(GlasgowAppletV2TestCase, applet=BenchmarkApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_simulation_test()
    async def test_sim(self, applet, ctx):
        await applet.benchmark_iface.sink(length=1000)
        await applet.benchmark_iface.source(length=1000)
