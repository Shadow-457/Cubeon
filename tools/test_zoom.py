"""Production zoom maths: equal motion at different FPS and unchanged normal input."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
package com.cubeon.client.hud;
public class ZoomTest {
    static void check(boolean ok, String why) { if (!ok) throw new AssertionError(why); }
    static void near(double a, double b, double tolerance, String why) {
        check(Math.abs(a-b) < tolerance, why + ": " + a + " vs " + b);
    }
    public static void main(String[] args) {
        near(Zoom.fovFactor(true, .1f), 1 / (1 + 3 * (1-Math.exp(-.1/.14))), .00001, "Hold starts configured zoom");
        for (int i=0; i<100; i++) Zoom.fovFactor(true, .02f);
        near(Zoom.fovFactor(true, .02f), .25, .00001, "Default 4x zoom");
        check(Zoom.lookFactor() < .25 && Zoom.lookFactor() > .15, "Fine aiming is slower at 4x");
        Zoom.onScroll(-1);
        for (int i=0; i<100; i++) Zoom.fovFactor(true, .02f);
        near(Zoom.fovFactor(true, .02f), .3, .00001, "Wheel adjusts view");
        Zoom.onScroll(100);
        for (int i=0; i<100; i++) Zoom.fovFactor(true, .02f);
        near(Zoom.fovFactor(true, .02f), .25, .00001, "Wheel respects ceiling");
        Zoom.onScroll(Double.NaN);
        near(Zoom.fovFactor(true, .02f), .25, .00001, "Invalid wheel ignored");
        double reference=0;
        for (int fps : new int[]{30, 60, 240}) {
            for (int i=0; i<100; i++) Zoom.fovFactor(false, .02f);
            float value=1;
            for (int i=0; i<fps; i++) value=Zoom.fovFactor(true, 1f/fps);
            if (reference != 0) near(reference, value, .00001, "FOV is independent of FPS");
            reference=value;
            var look = new Zoom.LookSmoother();
            double totalX=0, totalY=0;
            for (int i=0; i<fps; i++) {
                look.apply(120.0/fps, -60.0/fps, true, 1.0/fps, .2);
                totalX+=look.x; totalY+=look.y;
            }
            // Filtered velocity has the same continuous-time integral at every FPS.
            double expected = 24 * (1 - .035*(1-Math.exp(-1/.035)));
            near(totalX, expected, .000001, "Smoothed camera distance independent of FPS");
            near(totalY, -expected/2, .000001, "Pitch symmetry");
            for (int i=0; i<fps; i++) {
                look.apply(0, 0, true, 1.0/fps, .2);
                totalX+=look.x;
            }
            near(totalX, 24, .000001, "Smoothing preserves distance after settling");
            look.apply(7, -3, false, 1.0/fps, .2);
            near(look.x, 7, 1e-12, "Normal sensitivity restored immediately");
            near(look.y, -3, 1e-12, "No residual pitch after releasing zoom");
            look.apply(0, 0, true, 1.0/fps, .2);
            near(look.x, 0, 1e-12, "No old momentum on re-press");
            look.apply(10, -5, true, 1, .2);
            near(look.x, 2, 1e-12, "Long frame keeps zoom sensitivity");
            near(look.y, -1, 1e-12, "Long frame keeps zoom pitch sensitivity");
        }
        for (int i=0; i<200; i++) Zoom.fovFactor(false, .02f);
        check(!Zoom.isActive() && !Zoom.isHeld(), "Fully restored view");
        CubeonHudConfig.get().zoomFactor=Float.NaN;
        check(Float.isFinite(Zoom.fovFactor(true, .02f)), "Invalid config stays finite");
        System.out.println("Zoom defaults, wheel, ceiling, FOV easing, slow smooth look, FPS independence and immediate release passed.");
    }
}
'''

@unittest.skipUnless(shutil.which('java') and shutil.which('javac'), 'JDK required')
class ZoomTests(unittest.TestCase):
    def test_production_zoom(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            config = folder / 'CubeonHudConfig.java'
            config.write_text('''package com.cubeon.client.hud;
public class CubeonHudConfig {
    static final CubeonHudConfig CONFIG = new CubeonHudConfig();
    public float zoomFactor=4;
    public static CubeonHudConfig get() { return CONFIG; }
}''')
            harness = folder / 'ZoomTest.java'
            harness.write_text(HARNESS)
            source = ROOT / 'mod/src/main/java/com/cubeon/client/hud/Zoom.java'
            run = subprocess.run(['javac', '--release', '17', '-d', str(folder), str(source), str(config), str(harness)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            run = subprocess.run(['java', '-cp', str(folder), 'com.cubeon.client.hud.ZoomTest'], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            print(run.stdout.strip())

if __name__ == '__main__':
    unittest.main()
