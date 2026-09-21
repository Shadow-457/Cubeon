package com.cubeon.client;

import java.util.List;
import java.util.Set;
import java.util.TreeSet;

/**
 * Which names earn the Cubeon badge in front of a nametag.
 *
 * <p>The two sides of this never line up by accident. Minecraft draws a
 * nametag from the player's <em>Minecraft username</em> ({@code Player
 * .getName()}), while the launcher's identity payload carries the relay's
 * internal routing HANDLE as {@code name} and the human Minecraft username in
 * {@code minecraft_username}. An auto-minted handle looks like
 * {@code Player_ab12cd34} - a routing key, never a name anyone plays under.
 *
 * <p>Matching handles against in-game names therefore badges nobody: the badge
 * silently disappeared for friends and Cubeon strangers once the launcher
 * moved from claimed names to auto-minted handles, and only ever showed on
 * your own nametag (which is matched by player identity, not by name). Every
 * name the launcher can vouch for is added here - handles included, so an
 * older launcher, or an account whose handle really is its Minecraft name,
 * keeps working.
 *
 * <p>Minecraft-free on purpose: {@code mod/tools/SelfTest.java} covers it
 * against a bare JDK, which is the only way this matching rule can be tested
 * at all (the class that reads it, {@link Nametag}, needs Minecraft to run).
 */
public final class BadgeNames {

    private BadgeNames() {
    }

    /**
     * Every name this machine can prove is a Cubeon account, compared
     * case-insensitively (Minecraft usernames are, in practice). Never null;
     * empty when the launcher knows nothing yet, which badges only yourself.
     */
    public static Set<String> from(Bridge.Snapshot snapshot,
                                   List<Bridge.CubeonPlayer> players) {
        Set<String> names = new TreeSet<>(String.CASE_INSENSITIVE_ORDER);
        if (snapshot != null) {
            add(names, snapshot.you());
            add(names, snapshot.youMinecraftUsername());
            for (Bridge.Friend friend : snapshot.friends()) {
                if (friend == null) {
                    continue;
                }
                add(names, friend.name());
                add(names, friend.minecraftUsername());
            }
        }
        if (players != null) {
            for (Bridge.CubeonPlayer player : players) {
                if (player == null) {
                    continue;
                }
                add(names, player.name());
                add(names, player.minecraftUsername());
            }
        }
        return names;
    }

    private static void add(Set<String> into, String name) {
        if (name != null && !name.isEmpty()) {
            into.add(name);
        }
    }
}
