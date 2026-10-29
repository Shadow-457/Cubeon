"""Exercise production cosmetic poses: attachments, lighting, symmetry and pause."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / 'mod/src/main/java/com/cubeon/client'

HARNESS = r'''
import com.cubeon.client.cosmetics.*;
import java.nio.file.*;
import java.util.*;

public class AnimationTest {
    static void check(boolean ok, String why) {
        if (!ok) throw new AssertionError(why);
    }
    static void near(float a, float b, String why) {
        check(Math.abs(a - b) < 0.0001f, why + ": " + a + " vs " + b);
    }
    static float[] points(CosmeticCatalog.Item item, CosmeticAnimation.Frame frame) {
        var quads = CosmeticGeometry.quads(item, 0);
        float[] result = new float[quads.size() * 12];
        var posed = new CosmeticAnimation.PosedQuad();
        int n = 0;
        for (var quad : quads) {
            posed.set(quad, frame);
            for (int i = 0; i < 4; i++) {
                result[n++] = posed.x[i]; result[n++] = posed.y[i]; result[n++] = posed.z[i];
            }
        }
        return result;
    }
    static float difference(float[] a, float[] b) {
        float difference = 0;
        for (int i = 0; i < a.length; i++) difference = Math.max(difference, Math.abs(a[i] - b[i]));
        return difference;
    }
    static CosmeticGeometry.Quad pivot(String motion, float x, float y, float z) {
        var q = new CosmeticGeometry.Quad();
        q.motion = motion; q.pivotX = x; q.pivotY = y; q.pivotZ = z;
        Arrays.fill(q.x, x); Arrays.fill(q.y, y); Arrays.fill(q.z, z);
        q.normalY = 1;
        return q;
    }
    static void verifyFrames(CosmeticCatalog.Catalog catalog) {
        for (var item : catalog.items()) {
            var quads = CosmeticGeometry.quads(item, catalog.anchorX(item.slot));
            // Freeze the original mesh before running frames: caches are rest poses.
            var original = new ArrayList<float[]>();
            for (var q : quads) original.add(new float[]{q.x[0], q.y[0], q.z[0], q.normalX, q.normalY, q.normalZ, q.u[0], q.v[0]});
            var posed = new CosmeticAnimation.PosedQuad();
            for (int tick = 0; tick < 1920; tick++) {
                var frame = CosmeticAnimation.sample(tick / 30.0f, (tick % 120) / 120.0f, tick % 120 > 60);
                for (var q : quads) {
                    posed.set(q, frame);
                    float length = posed.normalX*posed.normalX + posed.normalY*posed.normalY + posed.normalZ*posed.normalZ;
                    near(length, 1, "Unit lighting normal: " + item.id);
                    float ax = posed.x[1]-posed.x[0], ay = posed.y[1]-posed.y[0], az = posed.z[1]-posed.z[0];
                    float bx = posed.x[3]-posed.x[0], by = posed.y[3]-posed.y[0], bz = posed.z[3]-posed.z[0];
                    near(ax*posed.normalX + ay*posed.normalY + az*posed.normalZ, 0, "Normal perpendicular to first edge");
                    near(bx*posed.normalX + by*posed.normalY + bz*posed.normalZ, 0, "Normal perpendicular to second edge");
                    for (int i = 0; i < 4; i++) {
                        check(Float.isFinite(posed.x[i]) && Float.isFinite(posed.y[i]) && Float.isFinite(posed.z[i]), "Finite coordinates");
                        check(Math.abs(posed.x[i]) < 20 && Math.abs(posed.y[i]) < 20 && Math.abs(posed.z[i]) < 20, "Bounded movement");
                        if ("head".equals(q.motion))
                            check(posed.x[i] < -4, "Pet turns must clear the player's head: " + item.id);
                    }
                }
            }
            for (int i = 0; i < quads.size(); i++) {
                var q = quads.get(i); var saved = original.get(i);
                check(Arrays.equals(saved, new float[]{q.x[0], q.y[0], q.z[0], q.normalX, q.normalY, q.normalZ, q.u[0], q.v[0]}), "Cache changed: " + item.id);
            }
            if (!item.id.endsWith("_pack")) {
                check(difference(points(item, CosmeticAnimation.sample(0, 0, false)),
                        points(item, CosmeticAnimation.sample(0.4f, 0, false))) > 0.05f, "Independent idle animation: " + item.id);
            }
        }
    }
    static void verifyAttachments(CosmeticCatalog.Item wings) {
        var body = pivot("body", -6, 1, 0);
        var root = pivot("wing", 1, 0, 2.45f);
        var mirror = pivot("wing", -1, 0, 2.45f); mirror.mirrored = true;
        var posed = new CosmeticAnimation.PosedQuad();
        for (int tick = 0; tick < 100; tick++) {
            var frame = CosmeticAnimation.sample(tick / 20.0f, 1, tick > 50);
            for (var q : List.of(body, root, mirror)) {
                posed.set(q, frame);
                near(posed.x[0], q.pivotX, "Attachment X");
                near(posed.y[0], q.pivotY, "Attachment Y");
                near(posed.z[0], q.pivotZ, "Attachment Z");
            }
            // Match all mirrored mesh vertices, including the feather caps.
            var left = new ArrayList<float[]>(); var right = new ArrayList<float[]>();
            for (var q : CosmeticGeometry.quads(wings, 0)) {
                posed.set(q, frame);
                var output = q.mirrored ? right : left;
                for (int i = 0; i < 4; i++) output.add(new float[]{Math.abs(posed.x[i]), posed.y[i], posed.z[i]});
            }
            Comparator<float[]> order = Comparator.comparingDouble((float[] p) -> Math.round(p[0]*10000))
                    .thenComparingDouble(p -> Math.round(p[1]*10000)).thenComparingDouble(p -> Math.round(p[2]*10000));
            left.sort(order); right.sort(order);
            check(left.size() == right.size(), "Mirrored wing counts");
            for (int i = 0; i < left.size(); i++) for (int axis = 0; axis < 3; axis++)
                near(left.get(i)[axis], right.get(i)[axis], "Mirrored wing vertex");
        }
        var tip = pivot("wing", 1, 0, 2.45f);
        tip.x[0] = 11;
        posed.set(tip, CosmeticAnimation.sample(0, 0, false)); float resting = posed.x[0];
        posed.set(tip, CosmeticAnimation.sample(0, 0, true));
        check(posed.x[0] > resting, "Gliding spreads the wing");
    }
    static void verifyTime(CosmeticCatalog.Item wings) {
        var tracker = new CosmeticAnimation.Tracker();
        var before = points(wings, tracker.sample(4, 0, false));
        var after = points(wings, tracker.sample(4.001f, 1, true));
        check(difference(before, after) < 0.1f, "Movement/glide transition must not snap");
        check(Arrays.equals(after, points(wings, tracker.sample(4.001f, 0, false))), "Pause must freeze the pose");
        near(difference(points(wings, tracker.sample(0, 1, true)),
                points(wings, CosmeticAnimation.sample(0, 1, true))), 0, "World age reset");
        check(difference(points(wings, CosmeticAnimation.sample(0.499f, 0, false)),
                points(wings, CosmeticAnimation.sample(0.500f, 0, false))) < 0.05f, "Subtick continuity");
        // An immutable submitted frame must survive a later render sample.
        var snapshot = tracker.sample(0.2f, 1, true);
        var saved = points(wings, snapshot);
        tracker.sample(0.4f, 0, false);
        check(Arrays.equals(saved, points(wings, snapshot)), "Deferred draw frame mutated");
        points(wings, CosmeticAnimation.sample(Float.NaN, Float.POSITIVE_INFINITY, false));
    }
    static int wingCycles(boolean sprinting) {
        var q = pivot("wing", 1, 0, 2.45f); q.x[0] = 11;
        var posed = new CosmeticAnimation.PosedQuad();
        var tracker = new CosmeticAnimation.Tracker();
        int cycles = 0; double previous = 0;
        for (int i = 0; i < 1200; i++) {
            posed.set(q, tracker.sample(i / 120f, sprinting ? 1 : 0, false, sprinting));
            double angle = Math.atan2(posed.z[0] - 2.45, posed.x[0] - 1);
            check(angle > .24 && angle < .49, "Wing stroke remains subtle");
            if (i > 0 && previous < .36 && angle >= .36) cycles++;
            previous = angle;
        }
        return cycles;
    }
    static void verifySprint(CosmeticCatalog.Item wings) {
        check(wingCycles(true) > wingCycles(false) * 2, "Sprint really speeds up wing beats");
        var tracker = new CosmeticAnimation.Tracker();
        var before = points(wings, tracker.sample(80, 0, false, false));
        var after = points(wings, tracker.sample(80.001f, 1, false, true));
        check(difference(before, after) < .03, "Sprint never jumps wing phase");
        float[] reference = null;
        for (int fps : new int[]{30, 60, 240}) {
            tracker = new CosmeticAnimation.Tracker();
            tracker.sample(0, 0, false, false);
            for (int i = 1; i <= fps * 3; i++)
                tracker.sample(i / (float)fps, 1, false, true);
            var pose = points(wings, tracker.sample(3, 1, false, true));
            if (reference != null) check(difference(reference, pose) < .002, "Frame-rate independent wing acceleration");
            reference = pose;
        }
        check(tracker.disabled() == null, "Off skips frame allocation");
        var posed = new CosmeticAnimation.PosedQuad();
        for (var quad : CosmeticGeometry.quads(wings, 0)) {
            posed.set(quad, null);
            check(Arrays.equals(posed.x, quad.x) && Arrays.equals(posed.y, quad.y)
                    && Arrays.equals(posed.z, quad.z), "Off draws exact cached rest mesh");
            near(posed.normalX, quad.normalX, "Rest normal X");
        }
        check(difference(points(wings, tracker.sample(20, 0, false)),
                points(wings, CosmeticAnimation.sample(20, 0, false))) < .0001, "Re-enable resets time");
    }
    static void verifyLegacy() {
        var q = pivot("none", 0, 0, 0); q.x[0] = 5; q.y[0] = 6; q.z[0] = 7;
        var posed = new CosmeticAnimation.PosedQuad();
        posed.set(q, CosmeticAnimation.sample(20, 1, true));
        near(posed.x[0], 5, "Unrigged X"); near(posed.y[0], 6, "Unrigged Y"); near(posed.z[0], 7, "Unrigged Z");
    }
    public static void main(String[] args) throws Exception {
        var catalog = CosmeticCatalog.Catalog.parse(Files.readString(Path.of(args[0])));
        verifyFrames(catalog);
        verifyAttachments(catalog.get("back_void_wings"));
        verifyTime(catalog.get("back_void_wings"));
        verifyLegacy();
        verifySprint(catalog.get("back_void_wings"));
        System.out.println("All 20 cosmetics: idle movement, sealed mirrored wings, fixed attachments, lighting, cache safety, smoothing, pause and world reset passed.");
    }
}
'''


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'A JDK is required')
class CosmeticAnimationTests(unittest.TestCase):
    def test_production_animation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            harness = root / 'AnimationTest.java'
            harness.write_text(HARNESS)
            sources = [JAVA / 'Json.java'] + [JAVA / 'cosmetics' / (name + '.java')
                       for name in ('CosmeticCatalog', 'CosmeticGeometry', 'CosmeticAnimation')]
            compiled = subprocess.run(['javac', '--release', '17', '-d', folder,
                                       *map(str, sources), str(harness)], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            tested = subprocess.run(['java', '-cp', folder, 'AnimationTest',
                                     str(ROOT / 'assets/cosmetics/catalog.json')],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
            print(tested.stdout.strip())


if __name__ == '__main__':
    unittest.main()
