"""Exercise actual enemy-health renderers/config with recorded GUI draws.

Minecraft fixtures supply entities and projection; production code filters them,
lays out bars, clamps health and persists the toggle. Gradle checks real APIs.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'mod/src/main'
GSON = next((Path.home() / '.gradle/caches/modules-2/files-2.1/com.google.code.gson/gson').glob('*/*/gson-*.jar'), None)
JOML = next((Path.home() / '.gradle/caches/modules-2/files-2.1/org.joml/joml').glob('*/*/joml-*.jar'), None)

FIXTURES = {
    'com/cubeon/client/hud/HealthCamera.java': '''
package com.cubeon.client.hud;
import net.minecraft.client.MinecraftClient;
import net.minecraft.util.math.Vec3d;
public class HealthCamera {
    public static Vec3d position(MinecraftClient.Camera camera) { return camera.getPos(); }
}''',
    'net/fabricmc/loader/api/FabricLoader.java': '''
package net.fabricmc.loader.api;
import java.nio.file.Path;
public class FabricLoader {
    public static FabricLoader getInstance() { return new FabricLoader(); }
    public Path getConfigDir() { return Path.of(System.getProperty("test.config")); }
}''',
    'com/cubeon/client/hud/CubeonHudClient.java': '''
package com.cubeon.client.hud;
public class CubeonHudClient {
    public static final Logger LOGGER = new Logger();
    public static class Logger { public void warn(String text, Object error) { throw new AssertionError(text); } }
}''',
    'com/cubeon/client/hud/CubeonHud.java': '''
package com.cubeon.client.hud;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
public class CubeonHud {
    public static void drawEnemyName(DrawContext draw, MinecraftClient client, String label, EnemyHealthBar.Pose pose) {
        draw.labels.add(new int[]{Math.round(pose.originX()), Math.round(pose.originY()), Math.round(pose.scale() * 1000)});
        draw.labelPoses.add(pose);
    }
    public static void drawEnemyBar(DrawContext draw, EnemyHealthBar.Pose pose, float fraction) {
        EnemyHealthBar.drawLocal((x,y,right,bottom,color) -> {
            float[] quad={pose.x(x,y),pose.y(x,y),pose.x(right,y),pose.y(right,y),
                    pose.x(right,bottom),pose.y(right,bottom),pose.x(x,bottom),pose.y(x,bottom)};
            draw.quads.add(quad);
            float left=Math.min(Math.min(quad[0],quad[2]),Math.min(quad[4],quad[6]));
            float top=Math.min(Math.min(quad[1],quad[3]),Math.min(quad[5],quad[7]));
            float end=Math.max(Math.max(quad[0],quad[2]),Math.max(quad[4],quad[6]));
            float base=Math.max(Math.max(quad[1],quad[3]),Math.max(quad[5],quad[7]));
            draw.precise.add(new float[]{left,top,end,base});
            draw.fill(Math.round(left),Math.round(top),Math.round(end),Math.round(base),color);
        },pose.scale(),fraction);
    }
}''',
    'net/minecraft/util/math/Vec3d.java': '''
package net.minecraft.util.math;
public class Vec3d {
    public final double x,y,z;
    public Vec3d(double x,double y,double z) { this.x=x;this.y=y;this.z=z; }
    public Vec3d add(double a,double b,double c) { return new Vec3d(x+a,y+b,z+c); }
    public Vec3d subtract(Vec3d other) { return new Vec3d(x-other.x,y-other.y,z-other.z); }
}''',
    'net/minecraft/util/math/Box.java': '''
package net.minecraft.util.math;
public class Box { public Box expand(double range) { return this; } }
''',
    'net/minecraft/scoreboard/AbstractTeam.java': '''
package net.minecraft.scoreboard;
public class AbstractTeam {
    public enum VisibilityRule { ALWAYS, NEVER, HIDE_FOR_OTHER_TEAMS, HIDE_FOR_OWN_TEAM }
    public VisibilityRule rule = VisibilityRule.ALWAYS;
    public VisibilityRule getNameTagVisibilityRule() { return rule; }
}''',
    'net/minecraft/entity/LivingEntity.java': '''
package net.minecraft.entity;
import net.minecraft.util.math.*;
import net.minecraft.scoreboard.AbstractTeam;
public class LivingEntity {
    public boolean alive=true, spectator, invisible, sneaking, allied, occluded, custom, named;
    public float health=10, maximum=20;
    public Vec3d pos = new Vec3d(0,1,-3);
    public double lastRenderX, lastRenderY=1, lastRenderZ=-3;
    public Vec3d physicsPos;
    public double getX() { return pos.x; }
    public double getY() { return pos.y; }
    public double getZ() { return pos.z; }
    public AbstractTeam team;
    public boolean isAlive() { return alive; }
    public boolean isSpectator() { return spectator; }
    public boolean isInvisible() { return invisible; }
    public boolean isSneaking() { return sneaking; }
    public boolean isTeammate(LivingEntity other) { return other.allied; }
    public boolean canSee(LivingEntity other) { return !other.occluded; }
    public double squaredDistanceTo(LivingEntity other) {
        double x=pos.x-other.pos.x,y=pos.y-other.pos.y,z=pos.z-other.pos.z;
        return x*x+y*y+z*z;
    }
    public Vec3d getLerpedPos(float delta) { return physicsPos == null ? pos : physicsPos; }
    public float getHeight() { return 1.8F; }
    public float getEyeHeight() { return 1.6F; }
    public Object getPose() { return null; }
    public float getEyeHeight(Object pose) { return 1.6F; }
    public Box getBoundingBox() { return new Box(); }
    public AbstractTeam getScoreboardTeam() { return team; }
    public String getName() { return "Enemy"; }
    public boolean hasCustomName() { return custom; }
    public boolean isCustomNameVisible() { return named; }
    public float getHealth() { return health; }
    public float getMaxHealth() { return maximum; }
}''',
    'net/minecraft/entity/player/PlayerEntity.java': '''
package net.minecraft.entity.player;
public class PlayerEntity extends net.minecraft.entity.LivingEntity {}
''',
    'net/minecraft/entity/mob/Monster.java': '''
package net.minecraft.entity.mob;
public interface Monster {}
''',
    'net/minecraft/client/world/ClientWorld.java': '''
package net.minecraft.client.world;
import java.util.*;
import java.util.function.Predicate;
import net.minecraft.entity.LivingEntity;
import net.minecraft.util.math.Box;
public class ClientWorld {
    public boolean cameraBlocked, barBlocked, edgeBlocked;
    public net.minecraft.util.hit.HitResult raycast(net.minecraft.world.RaycastContext ray) {
        boolean blocked = (cameraBlocked && ray.from.x > 5) || (barBlocked && ray.to.y > 2)
                || (edgeBlocked && Math.abs(ray.to.x) > .1)
                || entities.stream().anyMatch(entity -> entity.occluded);
        return new net.minecraft.util.hit.HitResult(blocked);
    }
    public List<LivingEntity> entities = new ArrayList<>();
    public <T extends LivingEntity> List<T> getEntitiesByClass(Class<T> type, Box box, Predicate<T> keep) {
        List<T> result = new ArrayList<>();
        for (LivingEntity entity: entities) if (type.isInstance(entity) && keep.test(type.cast(entity))) result.add(type.cast(entity));
        return result;
    }
}''',
    'net/minecraft/client/gui/DrawContext.java': '''
package net.minecraft.client.gui;
import java.util.*;
import net.minecraft.client.MinecraftClient.Font;
public class DrawContext {
    public List<float[]> precise = new ArrayList<>();
    public List<float[]> quads = new ArrayList<>();
    public List<com.cubeon.client.hud.EnemyHealthBar.Pose> labelPoses = new ArrayList<>();
    public List<int[]> fills = new ArrayList<>();
    public List<int[]> labels = new ArrayList<>();
    public int getScaledWindowWidth() { return 200; }
    public int getScaledWindowHeight() { return 100; }
    public void fill(int x,int y,int x2,int y2,int color) { fills.add(new int[]{x,y,x2,y2,color}); }
    public void drawTextWithShadow(Font font,String label,int x,int y,int color) { labels.add(new int[]{x,y}); }
    public void clear() { fills.clear(); labels.clear(); precise.clear(); quads.clear(); labelPoses.clear(); }
}''',
    'net/minecraft/util/hit/HitResult.java': '''
package net.minecraft.util.hit;
public class HitResult {
    public enum Type { MISS, BLOCK }
    private final boolean blocked;
    public HitResult(boolean blocked) { this.blocked=blocked; }
    public Type getType() { return blocked ? Type.BLOCK : Type.MISS; }
}''',
    'net/minecraft/world/RaycastContext.java': '''
package net.minecraft.world;
import net.minecraft.util.math.Vec3d;
import net.minecraft.entity.LivingEntity;
public class RaycastContext {
    public enum ShapeType { VISUAL }
    public enum FluidHandling { NONE }
    public final Vec3d from,to;
    public RaycastContext(Vec3d from,Vec3d to,ShapeType block,FluidHandling fluid,LivingEntity player) {
        this.from=from; this.to=to;
    }
}''',
    'net/minecraft/util/hit/EntityHitResult.java': '''
package net.minecraft.util.hit;
import net.minecraft.entity.LivingEntity;
public record EntityHitResult(LivingEntity getEntity) {}
''',
    'net/minecraft/client/MinecraftClient.java': '''
package net.minecraft.client;
import net.minecraft.client.world.ClientWorld;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.util.math.Vec3d;
public class MinecraftClient {
    public PlayerEntity player = new PlayerEntity();
    public ClientWorld world = new ClientWorld();
    public Object currentScreen, crosshairTarget;
    public Options options = new Options();
    public Font textRenderer = new Font();
    public Projection gameRenderer = new Projection();
    public static class Options { public boolean hudHidden; }
    public static class Font {
        public int fontHeight=9;
        public int getWidth(String label) { return label.length()*6; }
    }
    public static class Camera {
        public org.joml.Quaternionf rotation = new org.joml.Quaternionf();
        public Vec3d position = new Vec3d(0,1.6,0);
        public org.joml.Quaternionf getRotation() { return rotation; }
        public Vec3d getPos() { return position; }
    }
    public static class Projection {
        public double depth=0.5, horizontal=0;
        public org.joml.Matrix4f renderedViewProjection;
        public Camera camera = new Camera();
        public Camera getCamera() { return camera; }
        public Vec3d project(Vec3d point) {
            if(renderedViewProjection!=null) {
                var clip=renderedViewProjection.transform(new org.joml.Vector4f(
                        (float)(point.x-camera.position.x),(float)(point.y-camera.position.y),
                        (float)(point.z-camera.position.z),1));
                return new Vec3d(clip.x/clip.w,clip.y/clip.w,clip.z/clip.w);
            }
            var facing = new org.joml.Vector3d(point.x, point.y - 3.3, point.z + 3)
                    .rotate(new org.joml.Quaterniond(camera.rotation).conjugate());
            double perspective = Math.abs(-3 + facing.z) / 3;
            return new Vec3d(horizontal + facing.x * .4 / perspective, facing.y * .8 / perspective, depth);
        }
    }
}''',
    'probe/HealthTest.java': '''
package probe;
import com.cubeon.client.hud.*;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.entity.LivingEntity;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.entity.mob.Monster;
import net.minecraft.scoreboard.AbstractTeam;
import net.minecraft.util.math.Vec3d;
import java.nio.file.*;
import java.util.*;

public class HealthTest {
    static class Hostile extends LivingEntity implements Monster {}
    static MinecraftClient client = new MinecraftClient();
    static DrawContext draw = new DrawContext();
    static void require(boolean okay, String why) { if (!okay) throw new AssertionError(why); }
    static boolean interpolationProbe;
    static float frameDelta=.5F;
    static void render() {
        if (client.world != null && !interpolationProbe) for (var entity:client.world.entities) {
            entity.lastRenderX=entity.pos.x; entity.lastRenderY=entity.pos.y; entity.lastRenderZ=entity.pos.z;
        }
        draw.clear();
        EnemyHealthRenderer.render(draw, client, client.gameRenderer::project, frameDelta);
    }
    static void hidden(LivingEntity enemy, String why) {
        client.world.entities = new ArrayList<>(List.of(enemy)); render();
        require(draw.fills.isEmpty() && draw.labels.isEmpty(), why);
    }
    static void near(double actual,double expected,String why) {
        require(Math.abs(actual-expected)<.002,why+": actual="+actual+" expected="+expected);
    }
    static double[] gui(Vec3d point) {
        var projected=client.gameRenderer.project(point);
        return new double[]{(projected.x+1)*100,(1-projected.y)*50};
    }
    static void movingLabelPlane() {
        Hostile mob=new Hostile(); client.world.entities=new ArrayList<>(List.of(mob));
        interpolationProbe=true;
        double previousCenter=0,previousTop=0; int rolledFrames=0,rollovers=0;
        for(int frame=0;frame<120;frame++) {
            int tick=frame/6; frameDelta=(frame%6)/6F;
            double time=tick+frameDelta;
            mob.lastRenderX=-.2+(tick-1)*.01; mob.lastRenderY=1; mob.lastRenderZ=-3.5+(tick-1)*.005;
            mob.pos=new Vec3d(-.2+tick*.01,1,-3.5+tick*.005);
            // Physics history is deliberately unrelated to rendered movement.
            mob.physicsPos=new Vec3d(8,-3,2);
            client.gameRenderer.camera.position=new Vec3d(.08*Math.sin(time*.12),1.6,0);
            // Walking bob/hurt tilt live in the world matrix, independent of Camera.rotation.
            var projection=new org.joml.Matrix4f().perspective((float)Math.PI/2,2,.05F,100);
            client.gameRenderer.renderedViewProjection=projection
                    .rotateZ((float)(.09*Math.sin(time*.13))).rotateX((float)(.025*Math.cos(time*.07)));
            render();
            require(draw.quads.size()==2 && draw.labelPoses.size()==1,"Moving visible mob keeps name and health quads");
            Vec3d anchor=new Vec3d(mob.lastRenderX+(mob.pos.x-mob.lastRenderX)*frameDelta,
                    1+mob.getHeight()+.5,mob.lastRenderZ+(mob.pos.z-mob.lastRenderZ)*frameDelta);
            var origin=gui(anchor); var right=gui(anchor.add(EnemyHealthBar.NAME_WORLD_HEIGHT,0,0));
            var down=gui(anchor.add(0,-EnemyHealthBar.NAME_WORLD_HEIGHT,0));
            double rx=(right[0]-origin[0])/9,ry=(right[1]-origin[1])/9;
            double dx=(down[0]-origin[0])/9,dy=(down[1]-origin[1])/9;
            var label=draw.labelPoses.get(0);
            near(label.originX(),origin[0],"Mob label follows rendered anchor through tick rollover");
            near(label.originY(),origin[1],"Mob label uses current camera translation");
            near(label.rightX(),rx,"Label preserves projected right X");
            near(label.rightY(),ry,"Label preserves world-view roll");
            near(label.downX(),dx,"Label preserves projected down X");
            near(label.downY(),dy,"Label preserves projected down Y");
            near(label.scale(),Math.hypot(dx,dy),"Tilted label scale uses the full down vector");
            var quad=draw.quads.get(0);
            float[] local={-18,11,18,11,18,15,-18,15};
            for(int vertex=0;vertex<4;vertex++) {
                double x=local[vertex*2],y=local[vertex*2+1];
                near(quad[vertex*2],origin[0]+rx*x+dx*y,"Health corner follows label plane X");
                near(quad[vertex*2+1],origin[1]+ry*x+dy*y,"Health corner follows label plane Y");
            }
            double center=(quad[0]+quad[2])*.5,top=(quad[1]+quad[3])*.5;
            if(frame>0) require(Math.abs(center-previousCenter)<.25 && Math.abs(top-previousTop)<.25,
                    "Camera/entity movement remains continuous between frames and across ticks");
            if(Math.abs(quad[1]-quad[3])>.05) rolledFrames++;
            if(frame>0 && frame%6==0) rollovers++;
            previousCenter=center;previousTop=top;
        }
        require(rolledFrames>80 && rollovers==19,"Probe exercises tilted bars and repeated tick rollover");
        client.gameRenderer.renderedViewProjection=null;
        client.gameRenderer.camera.position=new Vec3d(0,1.6,0);
        interpolationProbe=false;frameDelta=.5F;
    }
    public static void main(String[] args) throws Exception {
        Path directory=Path.of(System.getProperty("test.config"));
        var old=new com.google.gson.JsonObject();
        old.addProperty("showFps",true); old.addProperty("fpsScale",1.25F);
        old.addProperty("motionBlur",true); old.addProperty("motionBlurStrength",3);
        old.addProperty("dynamicCrosshair",true);
        Files.writeString(directory.resolve("keyhud.json"),old.toString());
        CubeonHudConfig.load();
        require(CubeonHudConfig.get().showFps && !CubeonHudConfig.get().showEnemyHealth, "Old preferences preserved, health opt-in");
        require(CubeonHudConfig.get().cosmeticAnimations, "Old config defaults cosmetic animations on");
        require(CubeonHudConfig.get().wingDepth, "Old config defaults layered 3D wings on");
        require(!CubeonHudConfig.get().showOtherCosmetics, "Other cosmetics preference defaults OFF");
        require(!CubeonHudConfig.get().cameraMotionBlur, "Old blur never enables the new optional camera blur");
        require(CubeonHudConfig.get().cameraBlurIntensity==1f,"Old configs preserve the original 100% blur strength");
        require(CubeonHudConfig.get().showEmotes, "Old config defaults emote display on");
        require(CubeonHudConfig.get().emoteFavorites.length==8,"Old config gains default emote wheel");
        CubeonHudConfig.get().emoteFavorites=new String[]{"sit", "invalid", "laugh", "sit", null};
        PlayerEntity enemy=new PlayerEntity();
        client.player.pos=new Vec3d(0,1,0);
        hidden(enemy,"Off toggle must draw nothing");
        CubeonHudConfig.get().showEnemyHealth=true;
        CubeonHudConfig.get().cosmeticAnimations=false;
        CubeonHudConfig.get().wingDepth=false;
        CubeonHudConfig.get().showOtherCosmetics=true;
        CubeonHudConfig.get().cameraMotionBlur=true;
        CubeonHudConfig.get().cameraBlurIntensity=1.75f;
        CubeonHudConfig.get().showEmotes=false; CubeonHudConfig.save();
        var saved=com.google.gson.JsonParser.parseString(Files.readString(
                directory.resolve("cubeon-client-hud.json"))).getAsJsonObject();
        require(!saved.has("motionBlur") && !saved.has("motionBlurStrength")
                && !saved.has("dynamicCrosshair"),"Removed effects disappear on config save");
        require(saved.get("showFps").getAsBoolean() && saved.get("fpsScale").getAsFloat()==1.25F,
                "Removing old effects preserves other HUD preferences");
        CubeonHudConfig.get().showEnemyHealth=false;
        CubeonHudConfig.get().cosmeticAnimations=true;
        CubeonHudConfig.get().wingDepth=true;
        CubeonHudConfig.get().showOtherCosmetics=false;
        CubeonHudConfig.get().cameraMotionBlur=false;
        CubeonHudConfig.get().showEmotes=true; CubeonHudConfig.load();
        require(CubeonHudConfig.get().showEnemyHealth,"Health toggle persists");
        require(CubeonHudConfig.get().cameraMotionBlur,"Camera blur toggle persists independently of removed blur");
        require(CubeonHudConfig.get().cameraBlurIntensity==1.75f,"Blur intensity survives a save/reload");
        for(float value:new float[]{Float.NaN,Float.POSITIVE_INFINITY,Float.NEGATIVE_INFINITY,-1,100}) {
            CubeonHudConfig.get().cameraBlurIntensity=value; CubeonHudConfig.save(); CubeonHudConfig.load();
            float expected=Float.isFinite(value) ? Math.max(.25f,Math.min(2f,value)) : 1;
            require(CubeonHudConfig.get().cameraBlurIntensity==expected,"Malformed blur intensity normalizes safely");
        }
        require(Arrays.equals(CubeonHudConfig.get().emoteFavorites,new String[]{"sit", "laugh"}),
                "Favorite names persist in order, with invalid/duplicate values removed");
        require(!CubeonHudConfig.get().cosmeticAnimations, "Animation-off preference persists");
        require(!CubeonHudConfig.get().wingDepth, "Flat-wing preference persists independently");
        require(CubeonHudConfig.get().showOtherCosmetics, "Other cosmetics preference persists independently");
        require(!CubeonHudConfig.get().showEmotes, "Emote display-off preference persists");
        CubeonHudConfig.resetPositions();
        require(!CubeonHudConfig.get().cosmeticAnimations, "Reset positions preserves animation choice");
        require(!CubeonHudConfig.get().wingDepth, "Reset positions preserves wing depth choice");
        require(CubeonHudConfig.get().showOtherCosmetics, "Reset positions preserves other cosmetics choice");
        require(Arrays.equals(CubeonHudConfig.get().emoteFavorites,new String[]{"sit", "laugh"}),
                "HUD position reset preserves emote favorites");
        render();
        require(draw.fills.size()==2 && draw.labels.isEmpty(),"One player bar; no duplicate name");
        int[] background=draw.fills.get(0), fill=draw.fills.get(1);
        require(Arrays.equals(background,new int[]{82,61,118,65,EnemyHealthBar.BACKGROUND}),"Bar is beneath projected name at GUI scale");
        require(fill[2]-fill[0]==17 && fill[3]-fill[1]==2,"Half health, thin inset fill");
        // Subpixel motion is retained instead of snapping names/bars each frame.
        float previousX=draw.precise.get(0)[0];
        client.gameRenderer.horizontal=.0005; render();
        require(draw.precise.get(0)[0]>previousX && draw.precise.get(0)[0]-previousX<.1F,
                "Small camera movement keeps fractional bar position");
        client.gameRenderer.horizontal=0;
        // Crossing the former 2/3-pixel height threshold cannot collapse the fill.
        float previousFillHeight=0;
        for(int i=0;i<=20;i++) {
            enemy.pos=new Vec3d(0,1,-3/(.60+i*.0025)); render();
            var preciseFill=draw.precise.get(1);
            float fillHeight=preciseFill[3]-preciseFill[1];
            require(fillHeight>=.999F,"Distant health fill stays visible");
            if(i>0) require(Math.abs(fillHeight-previousFillHeight)<.02F,"Smooth resize without inset flicker");
            previousFillHeight=fillHeight;
        }
        enemy.pos=new Vec3d(0,1,-3);
        client.gameRenderer.camera.position=new Vec3d(8,1.6,0);
        client.world.cameraBlocked=true; hidden(enemy,"Camera wall occlusion, even with player line of sight");
        client.world.cameraBlocked=false;
        client.gameRenderer.camera.position=new Vec3d(0,1.6,0);
        client.world.barBlocked=true; hidden(enemy,"Label hidden behind wall above visible eyes");
        client.world.barBlocked=false;
        client.world.edgeBlocked=true; hidden(enemy,"Bar edge hidden behind wall");
        client.world.edgeBlocked=false;
        // Render history and physics history differ during entity movement.
        interpolationProbe=true;
        enemy.lastRenderY=0; enemy.pos=new Vec3d(0,2,-3); enemy.physicsPos=new Vec3d(0,-5,-3);
        render();
        require(Arrays.equals(draw.fills.get(0),background),"Bar follows vanilla render interpolation, ignoring physics history");
        interpolationProbe=false; enemy.physicsPos=null;
        enemy.pos=new Vec3d(0,1,-1.5); render();
        require(draw.fills.get(0)[2]-draw.fills.get(0)[0]==72 && draw.fills.get(0)[3]-draw.fills.get(0)[1]==8,"Near bar scales with name tag");
        enemy.pos=new Vec3d(0,1,-6); render();
        require(draw.fills.get(0)[2]-draw.fills.get(0)[0]==18 && draw.fills.get(0)[3]-draw.fills.get(0)[1]==2,"Far bar keeps same name-tag proportions");
        require(draw.fills.size()==2,"Thin distant bar retains health fill");
        enemy.pos=new Vec3d(0,1,-3);
        client.gameRenderer.camera.rotation.rotateX((float)Math.PI / 3); render();
        require(draw.fills.get(0)[2]-draw.fills.get(0)[0]==36,"Camera pitch preserves camera-facing label size");
        client.gameRenderer.camera.rotation.identity().rotateZ((float)Math.PI / 4); render();
        require(draw.fills.get(0)[2]-draw.fills.get(0)[0]==36,"Camera roll preserves camera-facing label size");
        client.gameRenderer.camera.rotation.identity();
        enemy.health=100; render(); require(draw.fills.get(1)[2]-draw.fills.get(1)[0]==34,"Overhealth clamped");
        enemy.health=Float.NaN; render(); require(draw.fills.size()==1,"Invalid health cannot overflow bar");
        enemy.health=5; render(); require(draw.fills.get(1)[4]==0xFFE87979,"Low health muted red");
        enemy.health=10;
        hidden(client.player,"No self bar"); hidden(new LivingEntity(),"No passive mob clutter");
        enemy.alive=false; hidden(enemy,"Dead"); enemy.alive=true;
        enemy.invisible=true; hidden(enemy,"Invisible"); enemy.invisible=false;
        enemy.spectator=true; hidden(enemy,"Spectator"); enemy.spectator=false;
        enemy.sneaking=true; hidden(enemy,"Sneaking name hidden"); enemy.sneaking=false;
        enemy.allied=true; hidden(enemy,"Teammate"); enemy.allied=false;
        enemy.occluded=true; hidden(enemy,"Through wall"); enemy.occluded=false;
        enemy.team=new AbstractTeam(); enemy.team.rule=AbstractTeam.VisibilityRule.NEVER;
        hidden(enemy,"Team hides name tag"); enemy.team=null;
        enemy.pos=new Vec3d(0,1,-25); hidden(enemy,"Beyond range"); enemy.pos=new Vec3d(0,1,-3);
        client.gameRenderer.depth=-.01; enemy.pos=new Vec3d(0,1,3);
        hidden(enemy,"Behind-camera negative reversed-Z depth cannot mirror into HUD");
        enemy.pos=new Vec3d(0,1,-3); client.gameRenderer.depth=.01;
        render(); require(draw.fills.size()==2,"Visible reversed-Z depth remains supported");
        client.gameRenderer.depth=1.01; hidden(enemy,"Behind camera/outside depth"); client.gameRenderer.depth=.5;
        client.gameRenderer.horizontal=2; hidden(enemy,"Offscreen"); client.gameRenderer.horizontal=0;
        client.currentScreen=new Object(); hidden(enemy,"Menu open"); client.currentScreen=null;
        client.options.hudHidden=true; hidden(enemy,"F1 hidden"); client.options.hudHidden=false;
        var world=client.world; client.world=null; render(); require(draw.fills.isEmpty(),"No world"); client.world=world;
        Hostile mob=new Hostile(); client.world.entities=new ArrayList<>(List.of(mob)); render();
        require(draw.fills.size()==2 && draw.labels.size()==1 && draw.labels.get(0)[1]+9<draw.fills.get(0)[1],"Mob name above bar");
        mob.pos=new Vec3d(0,1,-6); render();
        require(draw.labels.get(0)[2]==500 && draw.fills.get(0)[2]-draw.fills.get(0)[0]==18,"Distant mob name and bar share scale");
        mob.pos=new Vec3d(0,1,-1.5); render();
        require(draw.labels.get(0)[2]==2000 && draw.fills.get(0)[2]-draw.fills.get(0)[0]==72,"Near mob name and bar share scale");
        mob.pos=new Vec3d(0,1,-3);
        mob.custom=true; mob.named=true; render(); require(draw.labels.isEmpty(),"No duplicate visible custom mob name");
        mob.named=false; render(); require(draw.labels.size()==1,"Hidden custom tag gets a name");
        movingLabelPlane();
        client.world.entities=new ArrayList<>();
        for (int i=0;i<70;i++) client.world.entities.add(new PlayerEntity());
        render(); require(draw.fills.size()==64,"Crowds capped at 32 bars");
        require(EnemyHealthBar.fraction(-5,20)==0 && EnemyHealthBar.fraction(10,0)==0,"Invalid bounds");
        require(!EnemyHealthBar.onScreen(Double.NaN,0,0),"Invalid projection");
        System.out.println("Toggle persistence, filtering, near/far proportions, camera pitch/roll, names, clamping and crowd limit passed.");
    }
}''',
}


def mojang_source(source):
    replacements = {
        'net.minecraft.client.MinecraftClient': 'net.minecraft.client.Minecraft',
        'net.minecraft.client.gui.DrawContext': 'net.minecraft.client.gui.GuiGraphicsExtractor',
        'net.minecraft.client.world.ClientWorld': 'net.minecraft.client.multiplayer.ClientLevel',
        'net.minecraft.entity.LivingEntity': 'net.minecraft.world.entity.LivingEntity',
        'net.minecraft.entity.player.PlayerEntity': 'net.minecraft.world.entity.player.Player',
        'net.minecraft.entity.mob.Monster': 'net.minecraft.world.entity.monster.Enemy',
        'net.minecraft.scoreboard.AbstractTeam': 'net.minecraft.world.scores.Team',
        'net.minecraft.util.math.Vec3d': 'net.minecraft.world.phys.Vec3',
        'net.minecraft.util.math.Box': 'net.minecraft.world.phys.AABB',
        'net.minecraft.util.hit.EntityHitResult': 'net.minecraft.world.phys.EntityHitResult',
        'net.minecraft.util.hit.HitResult': 'net.minecraft.world.phys.HitResult',
        'MinecraftClient': 'Minecraft', 'DrawContext': 'GuiGraphicsExtractor',
        'ClientWorld': 'ClientLevel', 'PlayerEntity': 'Player', 'Monster': 'Enemy',
        'AbstractTeam': 'Team', 'VisibilityRule': 'Visibility', 'Vec3d': 'Vec3', 'Box': 'AABB',
        'getEntitiesByClass': 'getEntitiesOfClass', 'getNameTagVisibilityRule': 'getNameTagVisibility',
        'isSneaking': 'isShiftKeyDown', 'isTeammate': 'isAlliedTo', 'canSee': 'hasLineOfSight',
        'squaredDistanceTo': 'distanceToSqr', 'getLerpedPos': 'getPosition',
        'lastRenderX': 'xOld', 'lastRenderY': 'yOld', 'lastRenderZ': 'zOld',
        'getHeight': 'getBbHeight', 'getScoreboardTeam': 'getTeam',
        'getScaledWindowWidth': 'guiWidth', 'getScaledWindowHeight': 'guiHeight',
        'getWidth': 'width', 'fontHeight': 'lineHeight', 'textRenderer': 'font',
        'drawTextWithShadow': 'text', 'currentScreen': 'screen', 'crosshairTarget': 'hitResult',
        'hudHidden': 'hideGui', 'project(': 'projectPointToScreen(', '::project': '::projectPointToScreen',
        'net.minecraft.world.RaycastContext': 'net.minecraft.world.level.ClipContext',
        'RaycastContext': 'ClipContext', 'ShapeType': 'Block', 'FluidHandling': 'Fluid',
        'raycast(': 'clip(', 'getPos()': 'getPosition()',
        'client.world': 'client.level', 'public ClientLevel world': 'public ClientLevel level',
        'expand(': 'inflate(', 'getCamera()': 'getMainCamera()', 'getRotation()': 'rotation()',
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    # Package declarations in fixtures and the era's text rendering signature.
    for old, new in [('package net.minecraft.entity;', 'package net.minecraft.world.entity;'),
                     ('package net.minecraft.entity.player;', 'package net.minecraft.world.entity.player;'),
                     ('package net.minecraft.entity.mob;', 'package net.minecraft.world.entity.monster;'),
                     ('package net.minecraft.scoreboard;', 'package net.minecraft.world.scores;'),
                     ('package net.minecraft.util.math;', 'package net.minecraft.world.phys;'),
                     ('package net.minecraft.util.hit;', 'package net.minecraft.world.phys;'),
                     ('package net.minecraft.world;', 'package net.minecraft.world.level;'),
                     ('package net.minecraft.client.level;', 'package net.minecraft.client.multiplayer;'),
                     ('import net.minecraft.util.math.*;', 'import net.minecraft.world.phys.*;')]:
        source = source.replace(old, new)
    source = source.replace('int y,int color) { labels.add', 'int y,int color,boolean shadow) { labels.add')
    source = source.replace('client.gameRenderer::projectPointToScreen, frameDelta',
                            'frameDelta, client.screen == null && !client.options.hideGui, client.gameRenderer.camera.rotation, client.gameRenderer.camera.getPosition()')
    source = source.replace('public Vec3 projectPointToScreen(Vec3 point) { return renderer.projectPointToScreen(point); }',
                            'public Vec3 project(Vec3 point) { return renderer.projectPointToScreen(point); }')
    source = source.replace('getBoundingAABB', 'getBoundingBox')
    return source


@unittest.skipUnless(shutil.which('javac') and shutil.which('java') and GSON and JOML,
                     'A JDK and Gradle-cached Gson are required')
class EnemyHealthTests(unittest.TestCase):
    def test_actual_renderers_and_persistent_toggle(self):
        for namespace in ('yarn', 'mojang'):
            with self.subTest(namespace=namespace), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                sources = []
                fixtures=dict(FIXTURES)
                if namespace == 'mojang':
                    # The native camera-state adapter has a separate production-code probe.
                    fixtures['com/cubeon/client/hud/WorldHealthProjection.java'] = '''
package com.cubeon.client.hud;
import net.minecraft.client.MinecraftClient;
import net.minecraft.util.math.Vec3d;
public final class WorldHealthProjection {
    public static Frame current(MinecraftClient client) { return new Frame(client.gameRenderer); }
    public record Frame(MinecraftClient.Projection renderer) {
        public Vec3d camera() { return renderer.camera.getPos(); }
        public org.joml.Quaternionfc rotation() { return renderer.camera.getRotation(); }
        public Vec3d project(Vec3d point) { return renderer.project(point); }
    }
}'''
                for relative, source in fixtures.items():
                    if namespace == 'mojang':
                        # Derive fixture file path from its transformed package/public type.
                        source = mojang_source(source)
                        package = re.search(r'package ([\w.]+);', source)[1]
                        name = re.search(r'public (?:final )?(?:class|interface|record) (\w+)', source)[1]
                        relative = package.replace('.', '/') + '/' + name + '.java'
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(source)
                    sources.append(str(path))
                sources += [str(MAIN / 'java/com/cubeon/client/hud' / (name + '.java'))
                            for name in ('EnemyHealthBar', 'CubeonHudConfig', 'HudFeatures')]
                sources += [str(MAIN / 'java/com/cubeon/client' / name) for name in
                            ('Json.java', 'Bridge.java', 'ui/ClientTheme.java', 'emotes/EmoteState.java',
                             'emotes/EmotePose.java', 'emotes/EmoteFavorites.java')]
                sources.append(str(MAIN / ('java-overlay-api-' + namespace) /
                                   'com/cubeon/client/hud/EnemyHealthRenderer.java'))
                classes = root / 'classes'
                compile_result = subprocess.run(['javac', '--release', '17', '-cp', os.pathsep.join((str(GSON), str(JOML))),
                                                 '-d', str(classes), *sources], capture_output=True,
                                                text=True, timeout=60)
                self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
                result = subprocess.run(['java', '-Dtest.config=' + directory, '-cp',
                                         os.pathsep.join((str(classes), str(GSON), str(JOML))), 'probe.HealthTest'],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(namespace + ': ' + result.stdout.strip())

    @unittest.skipUnless(JOML, 'Gradle-cached JOML is required')
    def test_legacy_world_projection_and_frame_lifetime(self):
        event = '''package net.fabricmc.fabric.api.client.rendering.v1;
import java.util.function.Consumer;
import org.joml.Matrix4f;
import org.joml.Quaternionf;
import net.minecraft.client.world.ClientWorld;
import net.minecraft.util.math.Vec3d;
public class WorldRenderEvents {
    public static final Event AFTER_ENTITIES = new Event();
    public static class Event {
        public Consumer<Context> callback;
        public void register(Consumer<Context> value) { callback=value; }
    }
    public static class Camera {
        public Quaternionf rotation = new Quaternionf();
        public Quaternionf getRotation() { return rotation; }
        public Vec3d getPos() { return new Vec3d(0,1.6,0); }
    }
    public static class Counter {
        public float getTickDelta(boolean frozen) { return .5F; }
        public float getTickProgress(boolean frozen) { return .5F; }
    }
    public static class Context {
        public ClientWorld world;
        public Camera camera = new Camera();
        public Matrix4f projectionMatrix() { return new Matrix4f().perspective((float)Math.PI/2,2,0.05F,100); }
        public Camera camera() { return camera; }
        public ClientWorld world() { return world; }
        public float tickDelta() { return .5F; }
        public Counter tickCounter() { return new Counter(); }
    }
}'''
        probe = '''package probe;
import com.cubeon.client.hud.*;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.world.ClientWorld;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.util.math.Vec3d;
import net.fabricmc.fabric.api.client.rendering.v1.WorldRenderEvents;
import java.util.*;
public class LegacyTest {
    static MinecraftClient client = new MinecraftClient();
    static DrawContext draw = new DrawContext();
    static WorldRenderEvents.Context context = new WorldRenderEvents.Context();
    static void capture() { client.gameRenderer.camera.rotation.set(context.camera.rotation); context.world=client.world; WorldRenderEvents.AFTER_ENTITIES.callback.accept(context); }
    static void render() {
        for(var entity:client.world.entities) {
            entity.lastRenderX=entity.pos.x;entity.lastRenderY=entity.pos.y;entity.lastRenderZ=entity.pos.z;
        }
        draw.clear(); LegacyHealthProjection.render(draw,client);
    }
    static void require(boolean okay,String why) { if(!okay) throw new AssertionError(why); }
    public static void main(String[] args) {
        LegacyHealthProjection.register(); CubeonHudConfig.get().showEnemyHealth=true;
        require(CubeonHudConfig.get().emoteFavorites.length==8,"Old config gains default emote wheel");
        CubeonHudConfig.get().emoteFavorites=new String[]{"sit", "invalid", "laugh", "sit", null};
        PlayerEntity enemy=new PlayerEntity(); enemy.pos=new Vec3d(0,1,-3);
        client.world.entities=new ArrayList<>(List.of(enemy));
        render(); require(draw.fills.isEmpty(),"No world frame yet");
        capture(); render(); require(draw.fills.size()==2,"Perspective projects visible enemy");
        render(); require(draw.fills.isEmpty(),"World frame is consumed once");
        enemy.pos=new Vec3d(0,1,3); capture(); render(); require(draw.fills.isEmpty(),"Behind camera rejected before division");
        context.camera.rotation.rotateY((float)Math.PI); capture(); render();
        require(draw.fills.size()==2,"Camera rotation respected");
        capture(); client.world=new ClientWorld(); render(); require(draw.fills.isEmpty(),"Old world's projection rejected");
        client.world.entities=new ArrayList<>(List.of(enemy));
        CubeonHudConfig.get().showEnemyHealth=false; capture();
        CubeonHudConfig.get().showEnemyHealth=true; render(); require(draw.fills.isEmpty(),"Off frame invalidates cached matrix");
        System.out.println("World projection, camera rotation, behind-camera rejection and frame/world lifetime passed.");
    }
}'''
        for era in ('legacy', 'counter', 'progress', 'modern'):
            with self.subTest(era=era), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixtures = {key: value for key, value in FIXTURES.items() if key != 'probe/HealthTest.java'}
                fixtures['net/fabricmc/fabric/api/client/rendering/v1/WorldRenderEvents.java'] = event
                fixtures['probe/LegacyTest.java'] = probe
                if era == 'modern':
                    fixtures['probe/LegacyTest.java'] = probe.replace('LegacyHealthProjection.register();', '').replace('LegacyHealthProjection.render', 'WorldHealthProjection.render').replace('WorldRenderEvents.AFTER_ENTITIES.callback.accept(context);', 'WorldHealthProjection.capture(new org.joml.Matrix4f().rotation(new org.joml.Quaternionf(context.camera.rotation).conjugate()),context.projectionMatrix(),context.camera.getPos(),client.world,.5F);').replace('System.out.println("World projection', '''
        context.camera.rotation.identity();client.gameRenderer.camera.rotation.identity();
        enemy.pos=new Vec3d(0,1,-5); CubeonHudConfig.get().showEnemyHealth=true;
        capture(); render(); float normalX=draw.precise.get(0)[0]; float normalWidth=draw.precise.get(0)[2]-normalX;
        var projection=context.projectionMatrix(); var view=new org.joml.Matrix4f().rotateZ(.06F);
        WorldHealthProjection.capture(view,projection,context.camera.getPos(),client.world,.5F);render();
        require(Math.abs(draw.precise.get(0)[0]-normalX)>.1F,"Actual world view tilt moves HUD anchor");
        WorldHealthProjection.capture(new org.joml.Matrix4f(),new org.joml.Matrix4f().perspective((float)Math.PI/3,2,.05F,100),context.camera.getPos(),client.world,.5F);render();
        require(draw.precise.get(0)[2]-draw.precise.get(0)[0]>normalWidth*1.5F,"Current rendered FOV controls bar size");
        capture(); var previous=client.world;client.world=new ClientWorld();render();client.world=previous;render();
        require(draw.fills.isEmpty(),"Rejected world frame cannot reappear after world returns");
        System.out.println("World projection''')
                sources = []
                for relative, source in fixtures.items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(source)
                    sources.append(str(path))
                sources += [str(MAIN / 'java/com/cubeon/client/hud' / (name + '.java'))
                            for name in ('EnemyHealthBar', 'CubeonHudConfig', 'HudFeatures')]
                sources += [str(MAIN / 'java/com/cubeon/client' / name) for name in
                            ('Json.java', 'Bridge.java', 'ui/ClientTheme.java', 'emotes/EmoteState.java',
                             'emotes/EmotePose.java', 'emotes/EmoteFavorites.java')]
                sources += [str(MAIN / ('java-overlay-' + overlay) / 'com/cubeon/client/hud' / filename)
                            for overlay, filename in [('api-yarn', 'EnemyHealthRenderer.java'),
                                                       ('health-projection-modern' if era == 'modern' else 'health-' + era, 'WorldHealthProjection.java' if era == 'modern' else 'LegacyHealthProjection.java')]]
                classes = root / 'classes'
                libraries = os.pathsep.join((str(GSON), str(JOML)))
                compiled = subprocess.run(['javac', '--release', '17', '-cp', libraries,
                                           '-d', str(classes), *sources], capture_output=True, text=True, timeout=60)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                checked = subprocess.run(['java', '-Dtest.config=' + directory, '-cp',
                                          os.pathsep.join((str(classes), libraries)), 'probe.LegacyTest'],
                                         capture_output=True, text=True, timeout=30)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                print(era + ': ' + checked.stdout.strip())

    def test_menu_toggle_is_wired_for_every_bracket(self):
        matrix = json.loads((ROOT / 'mod/brackets.json').read_text())
        for bracket in matrix['brackets']:
            hud = next(overlay for overlay in bracket['overlays'] if overlay.startswith('hud-'))
            screen = (MAIN / ('java-overlay-' + hud) /
                      'com/cubeon/client/hud/screen/CubeonHudMenuScreen.java').read_text()
            self.assertIn('config.showEnemyHealth = !config.showEnemyHealth', screen, bracket['key'])
            self.assertIn('config.cosmeticAnimations = !config.cosmeticAnimations', screen, bracket['key'])
            layout = (MAIN / 'java/com/cubeon/client/ui/HudMenu.java').read_text()
            self.assertIn('new Feature("health",', layout, bracket['key'])
            self.assertIn('canvas.translate("cubeonclient.hud."+FEATURES[i].slot)', layout)


if __name__ == '__main__':
    unittest.main()
