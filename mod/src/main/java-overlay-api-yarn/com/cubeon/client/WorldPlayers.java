package com.cubeon.client;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayNetworkHandler;
import net.minecraft.client.network.PlayerListEntry;

/**
 * The usernames of the players actually in this world or server, straight from
 * the game's own player list.
 *
 * <p>Yarn-mapped twin of {@code java-overlay-api-mojang/WorldPlayers}: same
 * body, Minecraft names spelled the Yarn way ({@code MinecraftClient},
 * {@code ClientPlayNetworkHandler}, {@code PlayerListEntry}).
 *
 * <p>This is the launcher-facing half of the Online panel's question - "which
 * Cubeon players are HERE?" - and it can only come from Minecraft, not the
 * launcher. The profile's NAME does not survive authlib generations (6.x
 * {@code getName()} vs 7+ record {@code name()}), so that one lookup goes
 * through reflection; everything is wrapped in a catch-all, because this runs on
 * the render thread from a menu and a missing player list must cost an empty
 * panel, never a crash.
 */
public final class WorldPlayers {

    private WorldPlayers() {
    }

    /** Player usernames in the current world/server; empty when in a menu. */
    public static List<String> names() {
        try {
            MinecraftClient mc = MinecraftClient.getInstance();
            if (mc == null) {
                return List.of();
            }
            ClientPlayNetworkHandler connection = mc.getNetworkHandler();
            if (connection == null) {
                return List.of();   // title screen, or a world still loading
            }
            List<String> out = new ArrayList<>();
            for (PlayerListEntry info : connection.getPlayerList()) {
                if (info == null || info.getProfile() == null) {
                    continue;
                }
                String name = profileName(info.getProfile());
                if (name != null && !name.isEmpty()) {
                    out.add(name);
                }
            }
            return out;
        } catch (Throwable ex) {
            return List.of();
        }
    }

    /**
     * GameProfile's name across authlib generations: name() (26.x, a record
     * accessor) or getName() (1.20-1.21). Null when neither exists.
     */
    private static String profileName(Object profile) {
        for (String candidate : new String[] {"name", "getName"}) {
            try {
                Method method = profile.getClass().getMethod(candidate);
                Object value = method.invoke(profile);
                return value instanceof String text ? text : null;
            } catch (NoSuchMethodException ignored) {
                // try the next spelling
            } catch (Throwable ex) {
                return null;
            }
        }
        return null;
    }
}
