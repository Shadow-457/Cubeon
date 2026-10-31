"""Run each production HUD entry point with debug/F1/editor states.

Only downstream drawing is replaced with counters. The render method is copied
verbatim from each era; full Gradle builds validate the complete classes and APIs.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "mod/src/main"


def render_method(source):
    match = re.search(r"private static void render\([^)]*\)\s*\{", source)
    if not match:
        raise AssertionError("HUD render entry point is missing")
    depth = 1
    end = match.end()
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


FIXTURE = r'''
import java.util.*;

public class CubeonHud {
    enum Overlay { FPS, KEYS, ARMOR, PING, CPS }
    static final List<String> draws = new ArrayList<>();
    interface DrawAction { void draw(GuiBase gui, ClientBase client, int x, int y); }
    static void sampleClicks(ClientBase client) {}
    static void renderOverlay(GuiBase gui, ClientBase client, CubeonHudConfig config,
                              Overlay overlay, int width, int height, DrawAction draw) {
        draws.add(overlay.name());
        draw.draw(gui, client, 0, 0);
    }
    static void renderFps(GuiBase gui, ClientBase client, int x, int y) {}
    static void renderKeys(GuiBase gui, ClientBase client, int x, int y, boolean preview) {}
    static void renderArmor(GuiBase gui, ClientBase client, int x, int y) {}
    static void renderPing(GuiBase gui, ClientBase client, int x, int y) {}
    static void renderCps(GuiBase gui, ClientBase client, int x, int y) {}

    // PRODUCTION_RENDER

    static void check(String reason, String... expected) throws Exception {
        draws.clear();
        var method = Arrays.stream(CubeonHud.class.getDeclaredMethods())
                .filter(m -> m.getName().equals("render")).findFirst().orElseThrow();
        Object[] args = method.getParameterCount() == 1 ? new Object[]{new DrawContext()}
                : method.getParameterTypes()[0] == DrawContext.class
                ? new Object[]{new DrawContext(), .5f}
                : new Object[]{new GuiGraphicsExtractor(), new DeltaTracker()};
        method.invoke(null, args);
        if (!draws.equals(Arrays.asList(expected)))
            throw new AssertionError(reason + ": " + draws + " expected " + Arrays.toString(expected));
    }
    public static void main(String[] args) throws Exception {
        ClientBase client = CLIENT_INSTANCE;
        for (boolean hitboxes : new boolean[]{false, true}) {
            client.debug.hitboxes = hitboxes;
            for (boolean debug : new boolean[]{false, true}) {
                client.debug.visible = debug;
                client.options.debugEnabled = debug;
                check("Debug=" + debug + " hitboxes=" + hitboxes, "FPS", "KEYS", "ARMOR", "PING", "CPS", "HEALTH");
            }
        }
        // F1 and the editor still own visibility, even when F3 is active.
        client.options.hudHidden = true;
        client.options.hideGui = true;
        client.gui.hud.hidden = true;
        check("F1 hides every overlay");
        client.options.hudHidden = false;
        client.options.hideGui = false;
        client.gui.hud.hidden = false;
        client.currentScreen = client.screen = new MoveOverlayScreen();
        check("Editor avoids drawing the HUD twice");
        client.currentScreen = client.screen = null;
        CubeonHudConfig.get().showKeys = false;
        check("Per-overlay settings still apply with debug", "FPS", "ARMOR", "PING", "CPS", "HEALTH");
        CubeonHudConfig.get().showKeys = true;
        client.player = null;
        check("No player means no overlays");
        System.out.println("F3/debug/hitboxes stay visible; F1, editor, toggles and world exit passed.");
    }
}
class GuiBase {
    public int getScaledWindowWidth() { return 640; }
    public int getScaledWindowHeight() { return 360; }
    public int guiWidth() { return 640; }
    public int guiHeight() { return 360; }
}
class DrawContext extends GuiBase {}
class GuiGraphicsExtractor extends GuiBase {}
class DeltaTracker { public float getGameTimeDeltaPartialTick(boolean paused) { return .5f; } }
class MoveOverlayScreen {}
class ClientBase {
    public Object player = new Object(), currentScreen, screen;
    public Options options = new Options();
    public Debug debug = new Debug();
    public Gui gui = new Gui(this);
    public GameRenderer gameRenderer = new GameRenderer();
    public Debug getDebugHud() { return debug; }
    public Debug getDebugOverlay() { return debug; }
    public static class Options { public boolean debugEnabled, hudHidden, hideGui; }
    public static class Debug {
        public boolean visible, hitboxes;
        public boolean shouldShowDebugHud() { return visible; }
        public boolean showDebugScreen() { return visible; }
    }
    public static class Gui {
        private final ClientBase client;
        public Hud hud = new Hud();
        public Gui(ClientBase value) { client = value; }
        public Object screen() { return client.screen; }
    }
    public static class Hud { public boolean hidden; public boolean isHidden() { return hidden; } }
    public static class GameRenderer {
        public float[] project(Object point) { return new float[]{0, 0, 1}; }
        public Camera mainCamera() { return new Camera(); }
        public Camera getMainCamera() { return new Camera(); }
    }
    public static class Camera { public Object rotation() { return new Object(); } }
}
class MinecraftClient extends ClientBase {
    private static final MinecraftClient INSTANCE = new MinecraftClient();
    public static MinecraftClient getInstance() { return INSTANCE; }
}
class Minecraft extends ClientBase {
    private static final Minecraft INSTANCE = new Minecraft();
    public static Minecraft getInstance() { return INSTANCE; }
}
class CubeonHudConfig {
    public boolean showFps = true, showKeys = true, showArmor = true, showPing = true, showCps = true;
    private static final CubeonHudConfig INSTANCE = new CubeonHudConfig();
    public static CubeonHudConfig get() { return INSTANCE; }
}
class EnemyHealthRenderer {
    interface Projector { float[] project(Object point); }
    static void render(GuiBase gui, ClientBase client, Projector projector, float delta) { CubeonHud.draws.add("HEALTH"); }
    static void render(GuiBase gui, ClientBase client, float delta, boolean visible, Object rotation) {
        if (visible) CubeonHud.draws.add("HEALTH");
    }
}
class LegacyHealthProjection {
    static void render(GuiBase gui, ClientBase client) { CubeonHud.draws.add("HEALTH"); }
}
'''


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK required")
class HudDebugVisibilityTests(unittest.TestCase):
    def test_render_entry_points(self):
        adapters = sorted(MAIN.glob("java-overlay-hud-*/com/cubeon/client/hud/CubeonHud.java"))
        self.assertEqual(len(adapters), 8)
        for adapter in adapters:
            era = adapter.relative_to(MAIN).parts[0]
            method = render_method(adapter.read_text())
            client = "Minecraft" if "GuiGraphicsExtractor" in method else "MinecraftClient"
            source = FIXTURE.replace("// PRODUCTION_RENDER", method).replace(
                "CLIENT_INSTANCE", client + ".getInstance()")
            with self.subTest(era=era), tempfile.TemporaryDirectory(prefix="cubeon-hud-debug-") as temporary:
                folder = Path(temporary)
                harness = folder / "CubeonHud.java"
                harness.write_text(source)
                run = subprocess.run(["javac", "--release", "17", "-d", str(folder), str(harness)],
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                run = subprocess.run(["java", "-cp", str(folder), "CubeonHud"],
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                print(era + ": " + run.stdout.strip())


if __name__ == "__main__":
    unittest.main()
