package com.cubeon.client.modules;

import java.util.List;

import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.PlayerInfo;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.HitResult;

/**
 * Samples the game once per frame and hands the HUD modules their values.
 *
 * <p>Split from {@link HudText} on purpose. {@code HudText} is pure Java and
 * decides <em>what the lines say</em>; this class is the only place that reads
 * the game, so the version-sensitive bit is one small file and the drawing is
 * another, both per-bracket. Everything called here was checked with javap
 * against 1.20.1 and 26.1.2 and exists in both.
 */
public final class HudState {

    private HudState() {
    }

    /** The lines to draw this frame. Empty when nothing HUD-related is on. */
    public static List<String> lines() {
        Minecraft mc = Minecraft.getInstance();
        if (mc == null || mc.player == null) {
            return List.of();
        }
        Player player = mc.player;

        double x = player.getX();
        double y = player.getY();
        double z = player.getZ();
        int fps = mc.getFps();
        int ping = ping(mc);
        String keys = keys(mc);
        double reach = reach(mc, player);
        float scale = player.getAttackStrengthScale(0.0F);
        double cooldown = scale;
        int armor = player.getArmorValue();

        return HudText.build(fps, x, y, z, ping, keys, reach, cooldown, armor,
                Modules.get().all());
    }

    /** Distance from the player's eyes to whatever the crosshair is on. */
    private static double reach(Minecraft mc, Player player) {
        HitResult hit = mc.hitResult;
        if (hit == null) {
            return -1.0;
        }
        if (hit.getType() == HitResult.Type.BLOCK && hit instanceof BlockHitResult block) {
            var pos = block.getBlockPos();
            return Math.sqrt(player.distanceToSqr(
                    pos.getX() + 0.5, pos.getY() + 0.5, pos.getZ() + 0.5));
        }
        if (hit.getType() == HitResult.Type.ENTITY && hit instanceof EntityHitResult entity) {
            return player.distanceTo(entity.getEntity());
        }
        return -1.0;
    }

    /** Server latency in ms, or -1 when it cannot be read. */
    private static int ping(Minecraft mc) {
        try {
            if (mc.player == null || mc.getConnection() == null
                    || mc.getUser() == null) {
                return -1;
            }
            PlayerInfo info = mc.getConnection().getPlayerInfo(mc.getUser().getName());
            return info == null ? -1 : info.getLatency();
        } catch (Throwable ignored) {
            return -1;
        }
    }

    /** The movement keys currently held, in a fixed WASD-ish order. */
    private static String keys(Minecraft mc) {
        try {
            StringBuilder out = new StringBuilder();
            if (mc.options.keyUp.isDown()) {
                out.append('W');
            }
            if (mc.options.keyLeft.isDown()) {
                out.append('A');
            }
            if (mc.options.keyDown.isDown()) {
                out.append('S');
            }
            if (mc.options.keyRight.isDown()) {
                out.append('D');
            }
            if (mc.options.keyJump.isDown()) {
                out.append("  ");
                out.append("JUMP");
            }
            if (mc.options.keySprint.isDown()) {
                out.append("  SPRINT");
            }
            return out.toString();
        } catch (Throwable ignored) {
            return "";
        }
    }
}
