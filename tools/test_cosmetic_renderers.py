"""Run the real Yarn cosmetic renderers with hidden/decorated player name tags.

The game-facing objects are small draw-recording fixtures; catalogue, selection,
geometry and each complete renderer are production Java sources. Gradle builds
separately validate Minecraft's actual API. No window or network is needed.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / 'mod/src/main/java'
PACKAGE = 'com/cubeon/client/cosmetics/'
OVERLAYS = ('1.21.2', '1.21.5', '1.21.9', '1.21.11')

FIXTURES = {
    "com/cubeon/client/hud/CubeonHudConfig.java": '''
package com.cubeon.client.hud;
public class CubeonHudConfig {
    private static final CubeonHudConfig CONFIG = new CubeonHudConfig();
    public boolean cosmeticAnimations = true;
    public boolean wingDepth = true;
    public boolean showOtherCosmetics = false;
    public static CubeonHudConfig get() { return CONFIG; }
}
''',
    'net/minecraft/client/MinecraftClient.java': '''
package net.minecraft.client;
public class MinecraftClient {
    public static MinecraftClient instance = new MinecraftClient();
    public static MinecraftClient getInstance() { return instance; }
    public net.minecraft.entity.player.PlayerEntity player = new net.minecraft.entity.player.PlayerEntity(42, "Local");
    public World world = new World();
    public static class World {
        public net.minecraft.entity.player.PlayerEntity peer = new net.minecraft.entity.player.PlayerEntity(99, "Remote");
        public Object getEntityById(int id) { return id == 42 ? instance.player : id == 99 ? peer : null; }
    }
}''',
    'net/minecraft/entity/player/PlayerEntity.java': '''
package net.minecraft.entity.player;
public class PlayerEntity {
    public final int id; public final String name;
    public boolean invisible, spectator; public double distance;
    public PlayerEntity(int id, String name) { this.id=id; this.name=name; }
    public int getId(){return id;}
    public Name getName(){return new Name(name);}
    public record Name(String value){public String getString(){return value;}}
    public boolean isInvisible(){return invisible;}
    public boolean isSpectator(){return spectator;}
    public boolean isSprinting(){return false;}
    public boolean isFallFlying(){return false;}
    public double squaredDistanceTo(PlayerEntity other){return distance;}
    public net.minecraft.util.math.Vec3d getVelocity(){return new net.minecraft.util.math.Vec3d();}
}''',
    'net/minecraft/client/render/entity/state/PlayerEntityRenderState.java': '''
package net.minecraft.client.render.entity.state;
public class PlayerEntityRenderState { public int id; public Object displayName; public float age = 80; public boolean isGliding; }
''',
    'net/minecraft/util/math/Vec3d.java': '''
package net.minecraft.util.math;
public class Vec3d { public double horizontalLength() { return 0; } }
''',
    'net/minecraft/client/util/math/MatrixStack.java': '''
package net.minecraft.client.util.math;
public class MatrixStack {
    public int depth;
    private Entry value = new Entry(0, 0, 0, 0);
    private final java.util.ArrayDeque<Entry> saved = new java.util.ArrayDeque<>();
    public void push() { saved.push(value); depth++; }
    public void pop() { value = saved.pop(); depth--; }
    public void translate(float x, float y, float z) {
        double c = Math.cos(value.pitch), s = Math.sin(value.pitch);
        value = new Entry(value.x + x, value.y + (float)(c*y-s*z),
                          value.z + (float)(s*y+c*z), value.pitch);
    }
    public void rotateX(float pitch) { value = new Entry(value.x, value.y, value.z, value.pitch + pitch); }
    public Entry peek() { return value; }
    public record Entry(float x, float y, float z, float pitch) {
        public float[] point(float px, float py, float pz) {
            double c = Math.cos(pitch), s = Math.sin(pitch);
            return new float[]{x + px, y + (float)(c*py-s*pz), z + (float)(s*py+c*pz)};
        }
    }
}''',
    'net/minecraft/client/render/entity/model/PlayerEntityModel.java': '''
package net.minecraft.client.render.entity.model;
import net.minecraft.client.util.math.MatrixStack;
public class PlayerEntityModel {
    public Body body = new Body();
    public static class Body {
        public static float y, z, pitch;
        public void rotate(MatrixStack matrices) { applyTransform(matrices); }
        public void applyTransform(MatrixStack matrices) {
            matrices.translate(0, y / 16, z / 16); matrices.rotateX(pitch);
        }
    }
}''',
    'net/minecraft/client/render/entity/feature/FeatureRendererContext.java': '''
package net.minecraft.client.render.entity.feature;
public interface FeatureRendererContext<S, M> { M getModel(); }
''',
    'net/minecraft/client/render/entity/PlayerEntityRenderer.java': '''
package net.minecraft.client.render.entity;
import net.minecraft.client.render.entity.feature.FeatureRendererContext;
import net.minecraft.client.render.entity.model.PlayerEntityModel;
import net.minecraft.client.render.entity.state.PlayerEntityRenderState;
public class PlayerEntityRenderer implements FeatureRendererContext<PlayerEntityRenderState, PlayerEntityModel> {
    public PlayerEntityModel getModel() { return new PlayerEntityModel(); }
}''',
    'net/minecraft/client/render/entity/feature/FeatureRenderer.java': '''
package net.minecraft.client.render.entity.feature;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.client.render.VertexConsumerProvider;
import net.minecraft.client.render.command.OrderedRenderCommandQueue;
public class FeatureRenderer<S, M> {
    private final FeatureRendererContext<S, M> context;
    public FeatureRenderer(FeatureRendererContext<S, M> context) { this.context = context; }
    public M getContextModel() { return context.getModel(); }
    public void render(MatrixStack matrices, VertexConsumerProvider output, int light, S state, float a, float b) {}
    public void render(MatrixStack matrices, OrderedRenderCommandQueue output, int light, S state, float a, float b) {}
}''',
    'net/minecraft/util/Identifier.java': '''
package net.minecraft.util;
public record Identifier(String path) {
    public static Identifier of(String namespace, String path) { return new Identifier(path); }
}''',
    'net/minecraft/client/render/RenderLayer.java': '''
package net.minecraft.client.render;
import net.minecraft.util.Identifier;
public record RenderLayer(Identifier texture) {
    public static RenderLayer getEntityCutoutNoCull(Identifier texture) { return new RenderLayer(texture); }
}''',
    'net/minecraft/client/render/RenderLayers.java': '''
package net.minecraft.client.render;
import net.minecraft.util.Identifier;
public class RenderLayers {
    public static RenderLayer entityCutoutNoCull(Identifier texture) { return new RenderLayer(texture); }
}''',
    'net/minecraft/client/render/OverlayTexture.java': '''
package net.minecraft.client.render;
public class OverlayTexture { public static final int DEFAULT_UV = 0; }
''',
    'net/minecraft/client/render/VertexConsumer.java': '''
package net.minecraft.client.render;
import net.minecraft.client.util.math.MatrixStack;
import probe.Draws;
public class VertexConsumer {
    public VertexConsumer vertex(MatrixStack.Entry entry, float x, float y, float z) { Draws.vertices++; Draws.points.add(entry.point(x, y, z)); return this; }
    public VertexConsumer color(int r, int g, int b, int a) { return this; }
    public VertexConsumer texture(float u, float v) { return this; }
    public VertexConsumer overlay(int value) { return this; }
    public VertexConsumer light(int value) { return this; }
    public VertexConsumer normal(MatrixStack.Entry entry, float x, float y, float z) { return this; }
}''',
    'net/minecraft/client/render/VertexConsumerProvider.java': '''
package net.minecraft.client.render;
import probe.Draws;
public class VertexConsumerProvider {
    public VertexConsumer getBuffer(RenderLayer layer) {
        Draws.textures.add(layer.texture().path()); return new VertexConsumer();
    }
}''',
    'net/minecraft/client/render/command/OrderedRenderCommandQueue.java': '''
package net.minecraft.client.render.command;
import net.minecraft.client.render.*;
import net.minecraft.client.util.math.MatrixStack;
import probe.Draws;
public class OrderedRenderCommandQueue {
    public interface Geometry { void draw(MatrixStack.Entry entry, VertexConsumer consumer); }
    public void submitCustom(MatrixStack matrices, RenderLayer layer, Geometry geometry) {
        Draws.textures.add(layer.texture().path()); geometry.draw(matrices.peek(), new VertexConsumer());
    }
}''',
    'probe/Draws.java': '''
package probe;
import java.util.*;
public class Draws { public static List<String> textures = new ArrayList<>(); public static int vertices; public static List<float[]> points = new ArrayList<>(); }
''',
    'probe/RendererTest.java': r'''
package probe;
import com.cubeon.client.cosmetics.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.entity.PlayerEntityRenderer;
import net.minecraft.client.render.entity.state.PlayerEntityRenderState;
import net.minecraft.client.util.math.MatrixStack;

public class RendererTest {
    static final java.util.concurrent.atomic.AtomicInteger requests = new java.util.concurrent.atomic.AtomicInteger();
    static final java.util.concurrent.CountDownLatch started = new java.util.concurrent.CountDownLatch(1);
    static final java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
    static final List<String> BOTH = List.of("textures/cosmetics/back_void_wings.png",
                                            "textures/cosmetics/shoulder_star_owl.png");
    static Object renderer;
    static Method render;
    static void check(int id, Object name, List<String> expected) throws Exception {
        PlayerEntityRenderState state = new PlayerEntityRenderState();
        state.id = id; state.displayName = name;
        MatrixStack pose = new MatrixStack();
        Object output = render.getParameterTypes()[1].getConstructor().newInstance();
        Draws.textures.clear(); Draws.points.clear(); Draws.vertices = 0;
        render.invoke(renderer, pose, output, 0, state, 0.0f, 0.0f);
        if (!Draws.textures.equals(expected) || (Draws.vertices > 0) != !expected.isEmpty()) {
            throw new AssertionError("id=" + id + " name=" + name + " drew " + Draws.textures);
        }
        if (pose.depth != 0) throw new AssertionError("Leaked body transform");
        if (!expected.isEmpty()) {
            int vertex = 0;
            var catalog = CosmeticCatalog.get();
            var body = net.minecraft.client.render.entity.model.PlayerEntityModel.Body.class;
            float offsetY = body.getField("y").getFloat(null) / 16;
            float offsetZ = body.getField("z").getFloat(null) / 16;
            float pitch = body.getField("pitch").getFloat(null);
            double c = Math.cos(pitch), sin = Math.sin(pitch);
            for (String idKey : List.of("back_void_wings", "shoulder_star_owl")) {
                var item = catalog.get(idKey).forWingDepth(com.cubeon.client.hud.CubeonHudConfig.get().wingDepth);
                var posed = new CosmeticAnimation.PosedQuad();
                var animation = com.cubeon.client.hud.CubeonHudConfig.get().cosmeticAnimations
                        ? CosmeticAnimation.sample(state.age / 20, 0, false).forItem(item) : null;
                for (var quad : CosmeticGeometry.quads(item, catalog.anchorX(item.slot))) {
                    posed.set(quad, animation);
                    for (int i = 0; i < 4; i++) {
                        float x = posed.x[i] / 16, y = posed.y[i] / 16, z = posed.z[i] / 16;
                        float[] wanted = {x, offsetY + (float)(c*y-sin*z), offsetZ + (float)(sin*y+c*z)};
                        float[] actual = Draws.points.get(vertex++);
                        for (int axis = 0; axis < 3; axis++) {
                            if (Math.abs(actual[axis] - wanted[axis]) > 0.00001F)
                                throw new AssertionError("Misplaced " + idKey + " vertex on axis " + axis
                                        + ": " + actual[axis] + " expected " + wanted[axis]);
                        }
                    }
                }
            }
            if (vertex != Draws.points.size()) throw new AssertionError("Unexpected geometry");
        }
    }
    public static void main(String[] args) throws Exception {
        java.net.URL.setURLStreamHandlerFactory(protocol -> !protocol.equals("https") ? null : new java.net.URLStreamHandler() {
            protected java.net.URLConnection openConnection(java.net.URL url) {
                if (!url.getHost().equals("cubeon-skins.hamza-457-shahbaz.workers.dev")
                        || !url.getPath().equals("/cosmetics/remote.json")) throw new AssertionError("Unexpected network target");
                return new java.net.HttpURLConnection(url) {
                    public void connect(){} public void disconnect(){} public boolean usingProxy(){return false;}
                    public int getResponseCode() {
                        requests.incrementAndGet(); started.countDown();
                        try { if(!release.await(5,java.util.concurrent.TimeUnit.SECONDS))throw new AssertionError("Render waited for network"); }
                        catch(InterruptedException error){throw new RuntimeException(error);}
                        return 200;
                    }
                    public java.io.InputStream getInputStream(){return new java.io.ByteArrayInputStream(
                        "{\"back\":\"back_void_wings\",\"shoulder\":\"shoulder_star_owl\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8));}
                };
            }
        });
        CosmeticSelection.bind(Path.of(args[0]));
        String selection = Files.readString(Path.of(args[0]));
        if (!"back_void_wings".equals(CosmeticSelection.selectedWing()))
            throw new AssertionError("Equipped wing rig must enable N");
        Files.writeString(Path.of(args[0]), selection.replace("back_void_wings", "back_void_wings_small"));
        CosmeticSelection.bind(Path.of(args[0]));
        if (CosmeticSelection.selectedWing() != null)
            throw new AssertionError("Small wings must completely ignore N");
        Files.writeString(Path.of(args[0]), selection.replace("back_void_wings", "back_gear_pack"));
        CosmeticSelection.bind(Path.of(args[0]));
        if (CosmeticSelection.selectedWing() != null) throw new AssertionError("Pack must not enable N");
        Files.writeString(Path.of(args[0]), selection);
        CosmeticSelection.bind(Path.of(args[0]));
        Class<?> type = Class.forName("com.cubeon.client.cosmetics.CosmeticFeatureRenderer");
        renderer = type.getConstructor(PlayerEntityRenderer.class).newInstance(new PlayerEntityRenderer());
        render = Arrays.stream(type.getDeclaredMethods()).filter(m -> m.getName().equals("render")
                 && !m.isBridge()).findFirst().orElseThrow();
        check(42, null, BOTH);                       // F5 hides our own name tag.
        check(42, "[Team] Player", BOTH);            // Team/decorated text is irrelevant.
        check(99, "Player", List.of());              // Equal labels must not dress another player.
        check(99, null, List.of());
        if(requests.get()!=0)throw new AssertionError("Disabled peer setting must cause no requests");
        com.cubeon.client.hud.CubeonHudConfig.get().showOtherCosmetics=true;
        check(99, null, List.of());                 // Loading returns immediately, never blocks rendering.
        if(!started.await(2,java.util.concurrent.TimeUnit.SECONDS))throw new AssertionError("Peer lookup never started");
        check(42, null, BOTH);                      // Local selection remains instant while network blocks.
        release.countDown();
        long deadline=System.nanoTime()+2_000_000_000L;
        while(RemoteCosmetics.get("Remote").back()==null&&System.nanoTime()<deadline)Thread.sleep(5);
        check(99, "[Team] Decoration", BOTH);       // Authenticated peer selection uses native player name.
        check(99, null, BOTH);
        if(requests.get()!=1)throw new AssertionError("Every frame must reuse one cached response");
        var peer=MinecraftClient.instance.world.peer;
        peer.invisible=true; check(99,null,List.of()); peer.invisible=false;
        peer.spectator=true; check(99,null,List.of()); peer.spectator=false;
        peer.distance=4097; check(99,null,List.of()); peer.distance=0;
        com.cubeon.client.hud.CubeonHudConfig.get().showOtherCosmetics=false;
        check(99,null,List.of());                   // Turning OFF immediately hides previously loaded peers.
        check(42,null,BOTH);
        // Real model-space pose changes: standing body origin is zero, crouch moves
        // it down/back, swimming rotates it around X. Both items must follow.
        var body = net.minecraft.client.render.entity.model.PlayerEntityModel.Body.class;
        body.getField("y").setFloat(null, 3.2F);
        body.getField("z").setFloat(null, 4.0F);
        body.getField("pitch").setFloat(null, 0.5F);
        check(42, null, BOTH);
        body.getField("y").setFloat(null, 0);
        body.getField("z").setFloat(null, 0);
        body.getField("pitch").setFloat(null, (float)-Math.PI / 2);
        check(42, null, BOTH);
        // Off keeps the complete rest mesh visible, including body transforms.
        com.cubeon.client.hud.CubeonHudConfig.get().cosmeticAnimations = false;
        check(42, null, BOTH);
        com.cubeon.client.hud.CubeonHudConfig.get().cosmeticAnimations = true;
        check(42, null, BOTH);
        // Switching depth selects the four-quad mesh and matching texture instantly.
        com.cubeon.client.hud.CubeonHudConfig.get().wingDepth = false;
        var flatTextures = List.of("textures/cosmetics/back_void_wings_flat.png", BOTH.get(1));
        check(42, null, flatTextures);
        int flatCount = Draws.vertices;
        int expectedFlat = 16 + CosmeticGeometry.quads(CosmeticCatalog.get().get("shoulder_star_owl"), -7).size() * 4;
        if (flatCount != expectedFlat) throw new AssertionError("Flat wings must submit only sixteen vertices");
        com.cubeon.client.hud.CubeonHudConfig.get().cosmeticAnimations = false;
        check(42, null, flatTextures);
        com.cubeon.client.hud.CubeonHudConfig.get().cosmeticAnimations = true;
        com.cubeon.client.hud.CubeonHudConfig.get().wingDepth = true;
        check(42, null, BOTH);
        if (Draws.vertices <= flatCount * 10) throw new AssertionError("Depth OFF must reduce geometry work");
        MinecraftClient.instance.player = null;
        check(42, null, List.of());                  // Leaving a world is harmless.
        MinecraftClient.instance = null;
        check(42, null, List.of());
        System.out.println("Body poses, player identity, motion OFF, and instant 3D/flat texture/mesh switching passed.");
    }
}''',
}


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'A JDK is required')
class CosmeticRendererTests(unittest.TestCase):
    def test_renderers_draw_local_player_without_a_name_tag(self):
        for overlay in OVERLAYS:
            with self.subTest(overlay=overlay), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                sources = []
                for relative, source in FIXTURES.items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(source, encoding='utf-8')
                    sources.append(str(path))
                sources += [str(JAVA / 'com/cubeon/client/Json.java')]
                sources += [str(JAVA / PACKAGE / (name + '.java')) for name in
                            ('CosmeticCatalog', 'CosmeticSelection', 'CosmeticGeometry', 'CosmeticAnimation', 'WingAction', 'RemoteCosmetics', 'CosmeticView')]
                sources += [str(ROOT / 'mod/src/main/java-overlay-api-yarn' / PACKAGE / 'CosmeticPlayers.java')]
                sources += [str(ROOT / ('mod/src/main/java-overlay-cosmetics-' + overlay) /
                                PACKAGE / 'CosmeticFeatureRenderer.java')]
                classes = root / 'classes'
                compiled = subprocess.run(['javac', '--release', '17', '-d', str(classes), *sources],
                                          capture_output=True, text=True, timeout=60)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                resource = classes / 'assets/cubeon-client/cosmetics/catalog.json'
                resource.parent.mkdir(parents=True)
                shutil.copyfile(ROOT / 'assets/cosmetics/catalog.json', resource)
                selection = root / 'cubeon-cosmetics.json'
                selection.write_text(json.dumps({'version': 1, 'shoulder': 'shoulder_star_owl',
                                                 'back': 'back_void_wings'}), encoding='utf-8')
                checked = subprocess.run(['java', '-cp', str(classes), 'probe.RendererTest', str(selection)],
                                         capture_output=True, text=True, timeout=30)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                print(overlay + ': ' + checked.stdout.strip())


if __name__ == '__main__':
    unittest.main()
