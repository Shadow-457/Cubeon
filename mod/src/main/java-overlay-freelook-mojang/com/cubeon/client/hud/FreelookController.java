package com.cubeon.client.hud;

import net.minecraft.client.Minecraft;
import net.minecraft.client.CameraType;

/** Native 26.x adapter; the keybind adapter supplies this era's screen/focus checks. */
public final class FreelookController {
    private FreelookController() {}
    public static boolean sync() {
        Minecraft mc = Minecraft.getInstance();
        if (mc == null) return false;
        int view = mc.options.getCameraType().ordinal();
        int next = Freelook.INSTANCE.update(CubeonHudKeybinds.freelookHeld(),
                CubeonHudKeybinds.freelookEligible(), mc.player, mc.level,
                mc.player == null ? 0 : mc.player.getYRot(),
                mc.player == null ? 0 : mc.player.getXRot(), view);
        if (next != view) mc.options.setCameraType(CameraType.values()[next]);
        return Freelook.INSTANCE.active();
    }
    public static boolean look(double dx, double dy) { return sync() && Freelook.INSTANCE.look(dx, dy); }
    public static boolean scroll(double notches) { return sync() && Freelook.INSTANCE.scroll(notches); }
}
