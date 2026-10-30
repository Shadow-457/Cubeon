package com.cubeon.client.hud;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.Perspective;

/** Refresh on tick, camera update, and input so release/menu/focus changes take effect immediately. */
public final class FreelookController {
    private FreelookController() {}
    public static boolean sync() {
        MinecraftClient mc = MinecraftClient.getInstance();
        if (mc == null) return false;
        boolean held = CubeonHudKeybinds.freelookHeld();
        boolean eligible = mc.player != null && mc.world != null && mc.currentScreen == null
                && mc.isWindowFocused() && mc.mouse.isCursorLocked()
                && mc.getCameraEntity() == mc.player && mc.player.isAlive() && !mc.player.isSleeping();
        int view = mc.options.getPerspective().ordinal();
        int next = Freelook.INSTANCE.update(held, eligible, mc.player, mc.world,
                mc.player == null ? 0 : mc.player.getYaw(),
                mc.player == null ? 0 : mc.player.getPitch(), view);
        if (next != view) mc.options.setPerspective(Perspective.values()[next]);
        return Freelook.INSTANCE.active();
    }
    public static boolean look(double dx, double dy) {
        return sync() && Freelook.INSTANCE.look(dx, dy);
    }
    public static boolean scroll(double notches) {
        return sync() && Freelook.INSTANCE.scroll(notches);
    }
}
