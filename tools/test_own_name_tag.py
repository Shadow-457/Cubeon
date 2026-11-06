"""Exercise the production own-name visibility hooks with native-free entities.

The version builds validate Minecraft signatures; this harness checks that the
local override respects perspective/F1 and never changes other nameplates.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
class LivingEntity {
 boolean invisible, spectator, passengers, crouched;
 boolean isInvisibleTo(LivingEntity p) { return invisible; }
 boolean isSpectator() { return spectator; }
 boolean hasPassengers() { return passengers; }
 boolean isVehicle() { return passengers; }
 boolean isSneaky() { return crouched; }
 boolean isDiscrete() { return crouched; }
}
class PlayerLikeEntity extends LivingEntity {}
class Avatar extends PlayerLikeEntity {}
class Perspective { boolean first; boolean isFirstPerson() { return first; } }
class Options {
 Perspective perspective = new Perspective();
 Perspective getPerspective() { return perspective; }
 Perspective getCameraType() { return perspective; }
}
class Client { Avatar player = new Avatar(); Options options = new Options(); }
class Minecraft extends Client {
 static Minecraft instance = new Minecraft();
 static Minecraft getInstance() { return instance; }
}
class MinecraftClient extends Client {
 static MinecraftClient instance = new MinecraftClient();
 static MinecraftClient getInstance() { return instance; }
 static boolean isHudEnabled() { return !CubeonHud.hidden; }
}
class CubeonHud { static boolean hidden; static boolean hudHidden() { return hidden; } }
class CubeonHudConfig {
 boolean showOwnNameTag;
 static CubeonHudConfig instance = new CubeonHudConfig();
 static CubeonHudConfig get() { return instance; }
}
class CallbackInfoReturnable<T> { T value; void setReturnValue(T v) { value = v; } }
public class HookTest {
 static OwnNameTagMixin hook = new OwnNameTagMixin() {};
 static java.lang.reflect.Method method;
 static Client client;
 static void expect(LivingEntity entity, double distance, Boolean expected) throws Exception {
  var result = new CallbackInfoReturnable<Boolean>();
  Object[] args = method.getParameterCount() == 2 ? new Object[]{entity, result} : new Object[]{entity, distance, result};
  method.invoke(hook, args);
  if (!java.util.Objects.equals(result.value, expected)) throw new AssertionError("Label override: " + result.value + " expected " + expected);
 }
 public static void main(String[] args) throws Exception {
  client = args[0].equals("mojang") ? Minecraft.instance : MinecraftClient.instance;
  method = OwnNameTagMixin.class.getDeclaredMethods()[0]; method.setAccessible(true);
  var self = client.player;
  expect(self, 4, null); // Disabled preserves Minecraft's decision.
  CubeonHudConfig.get().showOwnNameTag = true;
  expect(self, 4, true);
  expect(new Avatar(), 4, null); // Never touch another entity's label.
  client.options.perspective.first = true; expect(self, 4, false);
  client.options.perspective.first = false;
  CubeonHud.hidden = true; expect(self, 4, false); CubeonHud.hidden = false;
  self.invisible = true; expect(self, 4, false); self.invisible = false;
  self.spectator = true; expect(self, 4, false); self.spectator = false;
  self.passengers = true; expect(self, 4, false); self.passengers = false;
  if (method.getParameterCount() == 3) {
   expect(self, 4096, false); self.crouched = true;
   expect(self, 1024, false); expect(self, 4, true);
  }
  client.player = null; expect(self, 4, null);
 }
}
'''


class OwnNameTagTests(unittest.TestCase):
    def test_local_visibility_in_each_renderer_era(self):
        for era in ("legacy", "yarn-state", "yarn-avatar", "mojang"):
            with self.subTest(era=era), tempfile.TemporaryDirectory() as folder:
                dest = Path(folder)
                source = (ROOT / f"mod/src/main/java-overlay-name-tag-{era}/com/cubeon/client/mixin/OwnNameTagMixin.java").read_text()
                source = re.sub(r"^(?:package |import |\s*@Mixin|\s*@Inject)[^\n]*\n", "", source, flags=re.M)
                source = source.replace("com.cubeon.client.hud.CubeonHud.hudHidden()", "CubeonHud.hudHidden()")
                (dest / "OwnNameTagMixin.java").write_text(source)
                (dest / "HookTest.java").write_text(FIXTURE)
                compile_result = subprocess.run(["javac", "--release", "17", "-d", folder, str(dest / "OwnNameTagMixin.java"), str(dest / "HookTest.java")], capture_output=True, text=True, timeout=30)
                self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
                result = subprocess.run(["java", "-cp", folder, "HookTest", era], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
