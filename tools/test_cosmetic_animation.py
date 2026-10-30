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
        if (frame != null) frame = frame.forItem(item);
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
                var frame = CosmeticAnimation.sample(tick / 30.0f, (tick % 120) / 120.0f, tick % 120 > 60).forItem(item);
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
                        float bound = "wing".equals(q.motion) ? 55 : 20;
                        check(Math.abs(posed.x[i]) < bound && Math.abs(posed.y[i]) < bound && Math.abs(posed.z[i]) < bound, "Bounded movement");
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
            var frame = CosmeticAnimation.sample(tick / 20.0f, 1, tick > 50).forItem(wings);
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
    static void verifyDragon(CosmeticCatalog.Catalog catalog) {
        Object player = new Object(), world = new Object();
        String id = "back_ember_wings";
        var action = new WingAction();
        action.tick(true, true, true, player, world, id, 10);
        near(action.elapsed(player, world, 10), 0, "N starts immediately");
        near(action.elapsed(player, world, 9.98f), 0, "Subtick interpolation starts smoothly");
        check(action.elapsed(new Object(), world, 10) < 0, "Different player cannot inherit N");
        check(action.elapsed(player, new Object(), 10) < 0, "Different world cannot inherit N");
        action.tick(true, true, true, player, world, id, 10.25f);
        near(action.elapsed(player, world, 10.25f), .25f, "Keyboard repeat never restarts a beat");
        action.tick(false, false, true, player, world, id, 10.3f);
        action.tick(true, true, true, player, world, id, 10.4f);
        near(action.elapsed(player, world, 10.4f), .4f, "Rapid taps never snap an active beat");
        near(action.elapsed(player, world, 10.4f), .4f, "Paused entity age freezes the action");
        check(action.elapsed(player, world, 10 + WingAction.DURATION) < 0, "One-shot ends automatically");
        action.tick(true, true, false, player, world, id, 10.45f);
        check(action.elapsed(player, world, 10.45f) < 0, "Menu/focus/death/disabled cancels");
        action.tick(true, true, true, player, world, id, 10.5f);
        check(action.elapsed(player, world, 10.5f) < 0, "Held N cannot restart after a menu");
        action.tick(false, false, true, player, world, id, 10.55f);
        action.tick(true, true, true, player, world, id, 10.6f);
        near(action.elapsed(player, world, 10.6f), 0, "Fresh press starts after cancellation");
        action.tick(false, false, true, player, world, "back_frost_wings", 10.65f);
        check(action.elapsed(player, world, 10.65f) < 0, "Changing wing cancels the old action");
        action.tick(true, true, true, player, world, null, 10.7f);
        check(action.elapsed(player, world, 10.7f) < 0, "Packs and no wings ignore N");
        action.tick(false, false, true, player, world, id, 10.75f);
        action.tick(true, true, true, player, world, id, 10.8f);
        action.tick(false, false, true, player, world, id, 0);
        check(action.elapsed(player, world, 0) < 0, "Age reset cancels N");
        action.tick(true, true, true, player, world, id, Float.NaN);
        check(action.elapsed(player, world, Float.NaN) < 0, "Invalid time is harmless");
        var wings = catalog.get(id);
        var tracker = new CosmeticAnimation.Tracker();
        float[] baseline = points(wings, tracker.sample(20, 0, false, false));
        check(difference(baseline, points(wings, tracker.sample(20, 0, false, false, 0))) == 0,
                "Dragon entry starts at the exact normal pose");
        check(difference(baseline, points(wings, tracker.sample(20, 0, false, false, .001f))) < .003,
                "Dragon entry never snaps");
        check(difference(baseline, points(wings, tracker.sample(20, 0, false, false, .8f))) > 8,
                "Dragon beats have a visibly powerful stroke");
        check(difference(baseline, points(wings, tracker.sample(20, 0, false, false, WingAction.DURATION - .001f))) < .003,
                "Dragon exit returns smoothly to normal phase");
        var pet = catalog.get("shoulder_ember_fox");
        check(difference(points(pet, tracker.sample(20, 0, false, false)),
                points(pet, tracker.sample(20, 0, false, false, .8f))) == 0, "N only moves wings");
        var q = pivot("wing", 2, 0, 2.575f); q.x[0] = 41; q.y[0] = 18;
        var mirror = pivot("wing", -2, 0, 2.575f); mirror.x[0] = -41; mirror.y[0] = 18; mirror.mirrored = true;
        var posed = new CosmeticAnimation.PosedQuad();
        for (int i = 0; i < 390; i++) {
            var frame = tracker.sample(20, 0, false, false, i / 120f).forItem(wings);
            posed.set(q, frame);
            float x = posed.x[0], y = posed.y[0], z = posed.z[0];
            posed.set(mirror, frame);
            near(x, -posed.x[0], "Dragon mirror X"); near(y, posed.y[0], "Dragon mirror Y"); near(z, posed.z[0], "Dragon mirror Z");
            var root = pivot("wing", 2, 0, 2.575f);
            posed.set(root, frame);
            near(posed.x[0], 2, "Dragon shoulder attachment X"); near(posed.y[0], 0, "Dragon shoulder attachment Y");
            for (var quad : CosmeticGeometry.quads(wings, 0)) {
                posed.set(quad, frame);
                near(posed.normalX * posed.normalX + posed.normalY * posed.normalY + posed.normalZ * posed.normalZ,
                        1, "Dragon lighting normals stay unit length");
                for (int v = 0; v < 4; v++) check(Float.isFinite(posed.x[v]) && Float.isFinite(posed.y[v]) && Float.isFinite(posed.z[v]),
                        "Dragon geometry stays finite");
            }
        }
        float[] reference = null;
        for (int fps : new int[]{30, 60, 240}) {
            tracker = new CosmeticAnimation.Tracker();
            float[] result = null;
            for (int i = 0; i <= fps * 2; i++) result = points(wings, tracker.sample(20 + i / (float) fps, 0, false, false, i / (float) fps));
            if (reference != null) check(difference(reference, result) < .002, "Dragon action is independent of FPS");
            reference = result;
        }
    }
    static void verifyFeathers(CosmeticCatalog.Catalog catalog) {
        for (var item : catalog.items()) {
            if (item.feathers.isEmpty()) continue;
            var quads = CosmeticGeometry.quads(item, 0);
            check(quads.size() <= (item.id.endsWith("_small") ? 144 : 2556), "Lightweight mesh budget");
            check(item.texWidth <= 512 && item.texHeight <= 1024, "Old GPU texture budget");
            var posed = new CosmeticAnimation.PosedQuad();
            for (float elapsed : new float[]{-1, 0, .3f, .8f, 1.4f, 2.6f}) {
                var normal = new CosmeticAnimation.Tracker().sample(20, 0, false, false, item.wingFlare ? elapsed : -1);
                var flexed = normal.forItem(item);
                check(flexed.forItem(item) == flexed, "Item snapshot prepared only once");
                var byPoint = new HashMap<String, float[]>();
                float[] displacement = new float[item.feathers.size()];
                float[] nearest = new float[item.feathers.size()]; Arrays.fill(nearest, Float.MAX_VALUE);
                for (var q : quads) {
                    posed.set(q, flexed);
                    float[][] output = new float[4][];
                    for (int v = 0; v < 4; v++) {
                        output[v] = new float[]{posed.x[v], posed.y[v], posed.z[v]};
                        String key = q.x[v] + "," + q.y[v] + "," + q.z[v];
                        float[] previous = byPoint.putIfAbsent(key, output[v]);
                        if (previous != null) for (int axis = 0; axis < 3; axis++)
                            near(previous[axis], output[v][axis], "Feather caps/walls stay welded");
                    }
                    if (q.mirrored || q.normalZ != -1) continue;
                    posed.set(q, normal); // Shoulder stroke without the local feather bends.
                    for (int v = 0; v < 4; v++) for (int j = 0; j < item.feathers.size(); j++) {
                        var f = item.feathers.get(j);
                        float dx = q.x[v] - f.endX, dy = q.y[v] - f.endY;
                        float distance = dx*dx + dy*dy;
                        if (distance < nearest[j]) {
                            nearest[j] = distance;
                            displacement[j] = output[v][2] - posed.z[v];
                        }
                    }
                }
                if (elapsed == .8f && item.wingFlare) {
                    for (int j = 0; j < item.feathers.size(); j++)
                        check(Math.abs(displacement[j]) > .01f, "Every feather visibly bends: " + item.id + "/" + j);
                    float min = Float.MAX_VALUE, max = -Float.MAX_VALUE;
                    for (float value : displacement) { min = Math.min(min, value); max = Math.max(max, value); }
                    check(max - min > (item.id.endsWith("_small") ? .1f : .5f), "Feathers have distinct recoil");
                }
                if (elapsed != .8f || !item.id.startsWith("back_ember_")) continue;
                // T junctions must land on the same straight, deformed edge as the cap.
                for (var q : quads) {
                    if (q.mirrored || q.normalZ != -1) continue;
                    posed.set(q, flexed);
                    for (int v = 0; v < 4; v++) {
                        int next = (v + 1) % 4;
                        for (var other : quads) {
                            if (other.mirrored || other.normalZ != -1) continue;
                            for (int n = 0; n < 4; n++) {
                                float dx = q.x[next]-q.x[v], dy = q.y[next]-q.y[v];
                                float t = Math.abs(dx) > 0 ? (other.x[n]-q.x[v])/dx : (other.y[n]-q.y[v])/dy;
                                if (t <= 0 || t >= 1 || other.x[n] != q.x[v]+dx*t || other.y[n] != q.y[v]+dy*t) continue;
                                float[] actual = byPoint.get(other.x[n] + "," + other.y[n] + "," + other.z[n]);
                                near(actual[0], posed.x[v]*(1-t) + posed.x[next]*t, "No open X seam");
                                near(actual[1], posed.y[v]*(1-t) + posed.y[next]*t, "No open Y seam");
                                near(actual[2], posed.z[v]*(1-t) + posed.z[next]*t, "No open Z seam");
                            }
                        }
                    }
                }
            }
        }
    }
    static void verifySmallIgnoresN(CosmeticCatalog.Catalog catalog) {
        for (var item : catalog.items()) if (item.id.endsWith("_small")) {
            check(!item.wingFlare, "Small wings cannot opt into N");
            var tracker = new CosmeticAnimation.Tracker();
            for (int n = 0; n < 130; n++) {
                float t = 20 + n / 40f;
                float[] idle = points(item, tracker.sample(t, 0, false, false, -1));
                float[] pressed = points(item, tracker.sample(t, 0, false, false, n / 40f));
                check(Arrays.equals(idle, pressed), "N must not move a single small-wing vertex: " + item.id);
            }
            check(difference(points(item, tracker.sample(20, 0, false, false)),
                    points(item, tracker.sample(20.3f, 0, false, false))) > .01f, "Small wings retain normal gentle motion");
        }
    }
    static volatile float checksum;
    static void benchmark(CosmeticCatalog.Item item) {
        var quads = CosmeticGeometry.quads(item, 0);
        var tracker = new CosmeticAnimation.Tracker(); var posed = new CosmeticAnimation.PosedQuad();
        var bean = (com.sun.management.ThreadMXBean) java.lang.management.ManagementFactory.getThreadMXBean();
        if (bean.isThreadAllocatedMemorySupported()) bean.setThreadAllocatedMemoryEnabled(true);
        for (boolean enabled : new boolean[]{true, false}) {
            for (int run = 0; run < 2; run++) {
                int frames = run == 0 ? 400 : 3000;
                long thread = Thread.currentThread().getId();
                long allocated = bean.getThreadAllocatedBytes(thread), started = System.nanoTime();
                float sum = 0;
                for (int n = 0; n < frames; n++) {
                    var frame = enabled ? tracker.sample(n / 60f, 0, false, false, item.wingFlare ? n % 180 / 60f : -1).forItem(item) : tracker.disabled();
                    for (int q = 0; q < quads.size(); q++) { posed.set(quads.get(q), frame); sum += posed.z[0]; }
                }
                long nanos = System.nanoTime() - started;
                long bytes = bean.getThreadAllocatedBytes(thread) - allocated;
                checksum = sum;
                if (run == 1) {
                    check(bytes / frames < (enabled ? 1024 : 8), "Bounded allocations / static OFF skips work");
                    System.out.printf(Locale.ROOT, "%s: %d quads, %.3f ms/frame CPU pose, %d bytes/frame (%s).%n",
                            item.id, quads.size(), nanos / (double) frames / 1e6, bytes / frames, enabled ? "ON" : "OFF");
                }
            }
        }
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
        verifyFeathers(catalog);
        verifySmallIgnoresN(catalog);
        benchmark(catalog.get("back_ember_wings"));
        benchmark(catalog.get("back_ember_wings_small"));
        verifySprint(catalog.get("back_void_wings"));
        verifyDragon(catalog);
        System.out.println("All 25 cosmetics: idle movement, sealed mirrored wings, fixed attachments, lighting, cache safety, smoothing, pause, world reset and dragon N action passed.");
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
                       for name in ('CosmeticCatalog', 'CosmeticGeometry', 'CosmeticAnimation', 'WingAction')]
            compiled = subprocess.run(['javac', '--release', '17', '-d', folder,
                                       *map(str, sources), str(harness)], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            tested = subprocess.run(['java', '-cp', folder, 'AnimationTest',
                                     str(ROOT / 'assets/cosmetics/catalog.json')],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
            print(tested.stdout.strip())


if __name__ == '__main__':
    unittest.main()
