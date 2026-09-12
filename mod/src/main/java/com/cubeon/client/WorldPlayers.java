package com.cubeon.client;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.client.multiplayer.PlayerInfo;

/*
 * The usernames of the players actually in this world or server, straight from
 * the game's own player list.
 *
 * This is the other half of the Online panel's question - "which Cubeon players
 * are HERE?" - and it can only come from Minecraft, not from the launcher: the
 * launcher knows who its account holders are, but has no idea who joined your
 * server. The panel intersects these names with Bridge.players() (and the
 * roster), which is how a Cubeon name in the tab list earns its row.
 *
 * Minecraft.getConnection() and ClientPacketListener.getOnlinePlayers() carry
 * the same shape from 1.20.1 through 26.1.2 (the latter checked against the
 * shipped jar's method table), so they are called directly. The profile's NAME
 * does not: 1.20.1's authlib GameProfile exposes getName(), while 26's authlib
 * 9 turned GameProfile into a record with name() - and PlayerInfo has no name
 * accessor of its own to hide the difference. That one lookup goes through
 * reflection, trying both spellings; everything is wrapped in one catch-all,
 * because this runs on the render thread from a menu and a missing player list
 * must cost an empty panel, never a crash.
 */
public final class WorldPlayers {

    private WorldPlayers() {
    }

    /** Player usernames in the current world/server; empty when in a menu. */
    public static List<String> names() {
        try {
            Minecraft mc = Minecraft.getInstance();
            if (mc == null) {
                return List.of();
            }
            ClientPacketListener connection = mc.getConnection();
            if (connection == null) {
                return List.of();   // title screen, or a world still loading
            }
            List<String> out = new ArrayList<>();
            for (PlayerInfo info : connection.getOnlinePlayers()) {
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
     * accessor) or getName() (1.20-1.21). Null when neither exists - the row
     * is simply skipped, which is what a future rename should cost.
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

