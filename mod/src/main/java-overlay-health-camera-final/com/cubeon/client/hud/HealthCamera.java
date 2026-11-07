package com.cubeon.client.hud;

import net.minecraft.client.render.Camera;
import net.minecraft.util.math.Vec3d;

public final class HealthCamera {
    private HealthCamera() {}
    public static Vec3d position(Camera camera) { return camera.getCameraPos(); }
}
