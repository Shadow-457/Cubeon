"""Run production blur math and audit native hooks for every cached game version."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "mod/src/main"
MATRIX_DATA = json.loads((ROOT / "mod/brackets.json").read_text())
MATRIX = MATRIX_DATA["brackets"]
HARNESS = r'''
package com.cubeon.client.hud;
public class CameraBlurTest {
    static void require(boolean okay, String why) { if (!okay) throw new AssertionError(why); }
    static void close(double actual, double wanted, double tolerance, String why) {
        require(Math.abs(actual-wanted) <= tolerance, why+": "+actual+" vs "+wanted);
    }
    static final Object WORLD = new Object();
    static void update(CameraBlur b, long t, double yaw, double pitch) {
        b.update(t, yaw, pitch, 70, 16.0/9, WORLD, true);
    }
    static float[] motion(int fps, boolean quantized) { return motion(fps,quantized,1); }
    static float[] motion(int fps, boolean quantized, double intensity) {
        CameraBlur b = new CameraBlur();
        b.update(1_000_000_000L,179,0,70,16.0/9,WORLD,true,intensity);
        for (int i=1; i<=fps; i++) {
            double t=(double)i/fps;
            double yaw=179+90*t;
            if(yaw>180) yaw-=360;
            double pitch=20*t;
            b.update(1_000_000_000L + Math.round(t*1e9),
                    quantized ? (float)yaw : yaw, quantized ? (float)pitch : pitch,
                    70,16.0/9,WORLD,true,intensity);
        }
        require(b.moving(), "A rotating camera blurs at "+fps+" FPS");
        return new float[]{b.x(), b.y()};
    }
    public static void main(String[] args) {
        double scale=2*Math.tan(Math.toRadians(70)/2);
        double x=Math.toRadians(90)*CameraBlur.EXPOSURE_SECONDS/(scale*16.0/9);
        double y=-Math.toRadians(20)*CameraBlur.EXPOSURE_SECONDS/scale;
        // Sample a mouse independently of render frames, including VSync and
        // render rates above mouse polling. Test every steady frame, not just
        // a conveniently moving last frame.
        for (int hz : new int[]{125, 1000}) for (int fps : new int[]{30,60,144,240,1000,2000}) {
            CameraBlur polled = new CameraBlur();
            update(polled,1_000_000_000L,0,0);
            double total=0; int count=0;
            for(int i=1;i<=2*fps;i++) {
                double t=(double)i/fps;
                double input=Math.floor(t*hz+1e-8)/hz;
                update(polled,1_000_000_000L+Math.round(t*1e9),(float)(90*input),(float)(20*input));
                if(t>.5) {
                    require(polled.moving(),"Polled input must not flicker sharp at "+fps+" FPS / "+hz+" Hz");
                    close(polled.x(),x,x*.3,"Per-frame exposure stays stable at "+fps+" FPS / "+hz+" Hz");
                    total+=polled.x();count++;
                }
            }
            close(total/count,x,x*.025,"Average exposure matches at "+fps+" FPS / "+hz+" Hz");
            // Stop with repeated samples at high FPS: the sampling grace is
            // measured in milliseconds, and must clear within 12 ms + a frame.
            long end=3_000_000_000L;
            for(int i=1;i<=Math.ceil(.012*fps)+1;i++)
                update(polled,end+Math.round((double)i/fps*1e9),180,40);
            require(!polled.moving(),"Stopped mouse clears within the time-based idle window");
        }
        for(int fps:new int[]{30,60,144,240,1000,2000}) {
            for(double intensity:new double[]{.25,.5,1,1.25,2}) {
                float[] exposure=motion(fps,false,intensity);
                close(exposure[0],x*intensity,.000000004,"Intensity scales horizontal exposure at every FPS");
                close(exposure[1],y*intensity,.000000004,"Intensity scales vertical exposure at every FPS");
            }
            for(boolean quantized:new boolean[]{false,true}) {
                float[] exposure=motion(fps,quantized);
                close(exposure[0],x,quantized ? 0.000002 : 0.000000002,"Horizontal exposure independent of FPS");
                close(exposure[1],y,quantized ? 0.000002 : 0.000000002,"Vertical exposure independent of FPS");
            }
            CameraBlur fast = new CameraBlur();
            update(fast, 1_000_000_000L, 0, 0);
            for(int i=1;i<=fps;i++) {
                double t=(double)i/fps;
                update(fast,1_000_000_000L+Math.round(t*1e9),3000*t,0);
            }
            close(fast.x(),.06,0.00000001,"Fast rotations cap consistently at low and high FPS");
            CameraBlur zoom = new CameraBlur();
            zoom.update(1_000_000_000L,0,0,70,16.0/9,WORLD,true);
            for(int i=1;i<=fps/10;i++) {
                double t=(double)i/fps;
                zoom.update(1_000_000_000L+Math.round(t*1e9),90*t,0,70-300*t,16.0/9,WORLD,true);
            }
            require(zoom.moving(),"Normal FOV changes must not disable blur only at low FPS");
        }
        CameraBlur b=new CameraBlur();
        update(b,1_000_000_000L,0,0);
        require(!b.moving(),"First frame has no history");
        update(b,1_016_000_000L,3,1);
        require(b.moving(),"Motion starts immediately");
        update(b,1_032_000_000L,3,1);
        require(!b.moving() && b.x()==0 && b.y()==0,"Stationary camera has no trails");
        update(b,1_048_000_000L,6,2);
        b.update(1_064_000_000L,7,2,70,16.0/9,new Object(),true);
        require(!b.moving(),"World changes clear exposure");
        update(b,1_080_000_000L,7,2);
        update(b,2_000_000_000L,8,2);
        require(!b.moving(),"Stalls do not smear the next image");
        update(b,2_016_000_000L,120,2);
        require(!b.moving(),"Camera cuts do not blur");
        b.update(2_032_000_000L,121,2,20,16.0/9,WORLD,true);
        require(!b.moving(),"FOV cuts reset motion");
        for(double bad:new double[]{Double.NaN, Double.POSITIVE_INFINITY}) {
            b.update(3_000_000_000L,bad,0,70,1,WORLD,true);
            require(!b.moving() && Float.isFinite(b.x()),"Invalid camera cannot reach shaders");
        }
        b.update(3_016_000_000L,0,0,70,0,WORLD,true);
        require(!b.moving(),"Zero-sized viewport stays sharp");
        update(b,4_000_000_000L,0,0); update(b,4_000_500_000L,2,2);
        require(b.moving() && Math.hypot(b.x(),b.y())<=.06000001,"Exposure is bounded at extreme speed");
        b.update(4_001_000_000L,21,21,70,1,WORLD,false);
        require(!b.moving(),"Disabled blur clears state");
        update(b,4_002_000_000L,22,22);
        require(!b.moving(),"Enabling starts without a stale vector");
        b.reset(); require(!b.moving(),"Explicit reset clears exposure");
        for(double invalid:new double[]{Double.NaN,Double.POSITIVE_INFINITY,Double.NEGATIVE_INFINITY})
            close(motion(60,false,invalid)[0],x,.000000004,"Invalid intensity safely restores default exposure");
        close(motion(60,false,-1)[0],x*.25,.000000004,"Negative intensity clamps to the minimum");
        close(motion(60,false,100)[0],x*2,.000000004,"Excessive intensity clamps to the maximum");
        System.out.println("Production camera blur: 30–2000 FPS, 125/1000 Hz mouse sampling, quantized cameras, yaw wrap, stop, cuts, stalls, invalid inputs and toggle passed");
    }
}
'''


class CameraBlurTests(unittest.TestCase):
    def test_production_math(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            harness = folder / "CameraBlurTest.java"
            harness.write_text(HARNESS)
            run = subprocess.run(["javac", "--release", "17", "-d", directory,
                                  str(MAIN / "java/com/cubeon/client/hud/CameraBlur.java"), str(harness)],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            run = subprocess.run(["java", "-cp", directory, "com.cubeon.client.hud.CameraBlurTest"],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            print(run.stdout.strip())

    def test_post_effect_saves_raw_history_before_presenting_blend(self):
        for era in ('legacy', 'post'):
            with self.subTest(era=era):
                root = MAIN / ('resources-overlay-camera-blur-' + era)
                path = root / ('assets/cubeon-client/shaders/post/motion_plus.json' if era == 'legacy'
                               else 'assets/cubeon-client/post_effect/motion_plus.json')
                blend, save, present = json.loads(path.read_text())['passes']
                if era == 'legacy':
                    self.assertEqual((blend['intarget'], blend['outtarget']), ('minecraft:main', 'swap'))
                    self.assertEqual((save['name'], save['intarget'], save['outtarget']),
                                     ('cubeon_motion_scene', 'minecraft:main', 'history'))
                    self.assertEqual((present['intarget'], present['outtarget']), ('swap', 'minecraft:main'))
                else:
                    self.assertEqual(blend['output'], 'swap')
                    self.assertEqual((save['program'], save['inputs'][0]['target'], save['output']),
                                     ('cubeon-client:post/motion_scene', 'minecraft:main', 'cubeon-client:history'))
                    self.assertEqual((present['inputs'][0]['target'], present['output']), ('swap', 'minecraft:main'))

    def test_temporal_exposure(self):
        harness = r'''package com.cubeon.client.hud;
public class TemporalTest {
 static void check(boolean v,String m){if(!v)throw new AssertionError(m);}
 static double exposure(int fps,double strength){
  var b=new TemporalBlur();Object world=new Object();long t=1_000_000_000L;
  b.update(t,0,0,70,1.6,world,true,strength);check(b.weight()==0,"First frame seeds history");
  double result=1;for(int n=1;n<=fps;n++){b.update(t+Math.round(n*1e9/fps),0,0,70,1.6,world,true,strength);check(b.weight()>=0&&b.weight()<=.450001,"History stays below half: current scene dominates");result=b.weight();}
  return result;
 }
 public static void main(String[] args){
  for(int fps:new int[]{15,30,60,144,240,1000}) for(double strength:new double[]{.25,1,2}) exposure(fps,strength);
  check(exposure(144,2)>exposure(144,.25),"Strength increases the short exposure");
  check(exposure(15,1)<exposure(144,1),"Slow frames cannot leave long trails");
  var b=new TemporalBlur();Object w=new Object();long t=1_000_000_000L;
  b.update(t,179,0,70,1.6,w,true,1);b.update(t+=10_000_000,-179,0,70,1.6,w,true,1);check(b.weight()>0,"Yaw wrap retains valid history");
  b.update(t+=10_000_000,0,0,70,1.6,w,true,1);check(b.weight()==0,"Camera cuts discard history");
  b.update(t+=10_000_000,0,0,90,1.6,w,true,1);check(b.weight()==0,"FOV cuts discard history");
  b.update(t+=10_000_000,0,0,90,2,w,true,1);check(b.weight()==0,"Aspect changes discard history");
  b.update(t+=200_000_000,0,0,90,2,w,true,1);check(b.weight()==0,"Stalls discard history");
  b.update(t+=10_000_000,0,0,90,2,new Object(),true,1);check(b.weight()==0,"World changes discard history");
  b.update(t+=10_000_000,Double.NaN,0,70,1.6,w,true,1);check(b.weight()==0,"Invalid cameras clear history");
  b.update(t,0,0,70,1.6,w,false,1);check(b.weight()==0,"Disabled effect clears history");
  System.out.println("Motion blur+: elapsed-time exposure, strength, yaw wrap, cuts, stalls and invalid inputs passed");
 }
}'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "TemporalTest.java"
            path.write_text(harness)
            run = subprocess.run(["javac", "--release", "17", "-d", directory,
                                  str(MAIN / "java/com/cubeon/client/hud/TemporalBlur.java"), str(path)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            run = subprocess.run(["java", "-cp", directory, "com.cubeon.client.hud.TemporalTest"], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            print(run.stdout.strip())

    def test_all_version_hooks_and_shaders(self):
        for bracket in MATRIX:
            with self.subTest(version=bracket["key"]):
                overlays = [o for o in bracket["overlays"] if o.startswith("camera-blur-")]
                self.assertEqual(len(overlays), 1)
                overlay = overlays[0]
                renderer = (MAIN / ("java-overlay-" + overlay) /
                            "com/cubeon/client/hud/blur/CameraBlurRenderer.java").read_text()
                if overlay not in ("camera-blur-legacy", "camera-blur-post"):
                    for method in ("withLocation", "withVertexShader", "withFragmentShader"):
                        self.assertNotIn(method + '("cubeon-client:', renderer,
                                         "Namespaced resources require native Identifier overloads")
                resource = MAIN / ("resources-overlay-" + overlay)
                config = json.loads((resource / "cubeon-client.camera-blur.mixins.json").read_text())
                self.assertFalse(config["required"])
                self.assertFalse("com.cubeon.client.hud.blur.CameraBlurRenderer".startswith(config["package"] + "."), "Renderer must be outside Mixin-owned packages")
                self.assertEqual(config["injectors"]["defaultRequire"], 0)
                for hook in config["client"]:
                    self.assertTrue((MAIN / ("java-overlay-" + overlay) / config["package"].replace(".", "/") / (hook + ".java")).is_file())
                fragment = next(p for p in resource.rglob("*.fsh") if p.stem in ("camera_blur", "cubeon_camera_blur"))
                code = fragment.read_text()
                self.assertIn("i < 12", code)
                self.assertIn("BlurVector * offset", code)
                self.assertIn("clamp(", code)
                self.assertNotIn("Prev", code)
                self.assertNotIn("BlurAmount", code)


def audit_targets():
    cache = Path.home() / ".gradle/caches/fabric-loom/minecraftMaven/net/minecraft"
    for bracket in MATRIX:
        version = bracket["compile_against"]
        paths = [p for p in cache.rglob("*.jar") if (p.name.startswith("minecraft-")
                 and (f"-{version}-" in p.name or p.name.endswith(f"-{version}.jar"))
                 and ("yarn" in p.name if bracket["mappings"] == "yarn" else "deobf" in p.name))]
        if not paths:
            raise AssertionError(f"Missing cached mapped game jar for {version}")
        mojang = bracket["mappings"] == "none"
        classes = ["net.minecraft.client.renderer.GameRenderer" if mojang else "net.minecraft.client.render.GameRenderer",
                   "net.minecraft.client.Minecraft" if mojang else "net.minecraft.client.MinecraftClient"]
        results = [subprocess.run(["javap", "-classpath", str(paths[0]), "-p", c],
                                  capture_output=True, text=True, timeout=30) for c in classes]
        for r in results:
            if r.returncode:
                raise AssertionError(r.stderr)
        renderer, client = [r.stdout for r in results]
        for method in ["render(", "close(", "renderLevel(" if mojang else "renderWorld("]:
            if method not in renderer:
                raise AssertionError(f"{version}: missing renderer hook {method}")
        if ("reloadResourcePacks(" if mojang else "reloadResources(") not in client:
            raise AssertionError(f"{version}: reload hook missing")
        if not mojang:
            expected = "double" if next(o for o in bracket["overlays"] if o.startswith("camera-blur-")) == "camera-blur-legacy" else "float"
            if f"private {expected} getFov(" not in renderer:
                raise AssertionError(f"{version}: wrong FOV callback return type")
        print(f"{version}: native world/render/close/reload/FOV hooks resolved")


def audit_jars():
    failures = []
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        harness = folder / "CameraBlurTest.java"
        harness.write_text(HARNESS)
        subprocess.run(["javac", "--release", "17", "-d", directory,
                        str(MAIN / "java/com/cubeon/client/hud/CameraBlur.java"), str(harness)], check=True)
        for bracket in MATRIX:
            jar = ROOT / "assets/jars" / MATRIX_DATA["jar_name"].format(version=MATRIX_DATA["mod_version"], key=bracket["key"])
            # Put the packaged class first, so this exercises the actual distributed math.
            result = subprocess.run(["java", "-cp", str(jar) + __import__('os').pathsep + directory,
                                     "com.cubeon.client.hud.CameraBlurTest"], capture_output=True, text=True, timeout=60)
            error = result.stderr if result.returncode else None
            if not error and any(o.startswith("zoom-") for o in bracket["overlays"]):
                with zipfile.ZipFile(jar) as archive:
                    if b"com/cubeon/client/hud/blur/CameraBlurRenderer" not in archive.read("com/cubeon/client/mixin/ZoomMixin.class"):
                        error = "Packaged zoom hook does not publish the final camera FOV"
            if error:
                failures.append(bracket["key"])
                print(f"{bracket['key']}: FAIL {error}")
            else:
                print(f"{bracket['key']}: packaged 30–2000 FPS behavior and zoom integration passed")
    if failures:
        raise AssertionError("Rebuild stale/incorrect client jars: " + " ".join(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", action="store_true")
    parser.add_argument("--jars", action="store_true")
    args = parser.parse_args()
    if not shutil.which("javac"):
        raise SystemExit("JDK required")
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(CameraBlurTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.targets:
        audit_targets()
    if args.jars:
        audit_jars()
