package com.cubeon.client.hud;

import java.lang.ref.WeakReference;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.world.ClientWorld;
import net.minecraft.util.math.Vec3d;
import org.joml.Matrix4f;
import org.joml.Matrix4fc;
import org.joml.Vector4f;

/** One world's actual view/FOV/bobbing matrices, consumed once by the following HUD. */
public final class WorldHealthProjection {
    private static final Matrix4f matrix = new Matrix4f();
    private static WeakReference<ClientWorld> world = new WeakReference<>(null);
    private static Vec3d camera;
    private static float delta;
    private static boolean ready;
    private WorldHealthProjection() {}
    public static void capture(Matrix4fc view, Matrix4fc projection, Vec3d position, ClientWorld level, float tick) {
        EnemyHealthFrame.begin();
        ready=false;
        if(!CubeonHudConfig.get().showEnemyHealth || level==null) return;
        matrix.set(projection).mul(view);
        camera=position;delta=tick;
        if(world.get()!=level) world=new WeakReference<>(level);
        ready=true;
    }
    public static void render(DrawContext draw, MinecraftClient client) {
        // 1.21.11 submits health labels beside the entity itself. Keeping that
        // work in the world queue prevents a pipelined world frame and the
        // later GUI extraction from disagreeing during a fast camera turn.
        if(EnemyHealthFrame.usesWorldLabels()) { ready=false; return; }
        if(!ready) return;
        ready=false;
        if(world.get()!=client.world) return;
        EnemyHealthRenderer.render(draw,client,WorldHealthProjection::project,delta);
    }
    private static Vec3d project(Vec3d point) {
        var relative=point.subtract(camera);
        var clip=matrix.transform(new Vector4f((float)relative.x,(float)relative.y,(float)relative.z,1));
        if(!Float.isFinite(clip.w)||clip.w<=0) return null;
        return new Vec3d(clip.x/clip.w,clip.y/clip.w,clip.z/clip.w);
    }
}
