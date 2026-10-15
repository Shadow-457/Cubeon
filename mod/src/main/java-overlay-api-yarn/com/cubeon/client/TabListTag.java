package com.cubeon.client;

import java.lang.reflect.Method;
import java.util.Set;
import java.util.TreeSet;

import net.minecraft.client.network.PlayerListEntry;
import net.minecraft.text.Style;
import net.minecraft.text.Text;
import net.minecraft.text.TextColor;

/**
 * Tags Cubeon players in the TAB LIST, so a friend reads as
 * {@code [Cubeon]Shadow} in green instead of a bare name.
 *
 * <p>Yarn-mapped twin of {@code java-overlay-api-mojang/TabListTag}: same body,
 * Minecraft names spelled the Yarn way ({@code Text}/{@code PlayerListEntry}).
 *
 * <p><b>Tab list only, on purpose.</b> The tab list is rendered on your screen
 * and nobody else's, so you can pick your friends out without the launcher
 * putting its name on anyone in public.
 *
 * <p><b>Cost.</b> {@code getPlayerName} runs once per row per frame while the
 * tab list is visible, so the name set is rebuilt only when the bridge moves
 * ({@link Bridge#revision()} / {@link Bridge#playersRevision()}), and it is a
 * case-insensitive {@link TreeSet} so a lookup needs no {@code toLowerCase}
 * copy.
 */
public final class TabListTag {

    /** The Cubeon accent, the same green the Friends button and logo use. */
    private static final TextColor CUBEON_GREEN = TextColor.fromRgb(0x83C13D);

    /** Cached Cubeon names, and the bridge revisions they were built from. */
    private static volatile Set<String> known =
            new TreeSet<>(String.CASE_INSENSITIVE_ORDER);
    private static volatile long knownRevision = -1;
    private static volatile long knownPlayersRevision = -1;

    private TabListTag() {
    }

    /**
     * A tab row's Minecraft username, or null if it cannot be read.
     *
     * <p><b>Reflection is deliberate and load-bearing here.</b> authlib 7 turned
     * {@code GameProfile} into a record and renamed {@code getName()} to
     * {@code name()}. That rename lands INSIDE the 1.20-1.21 range (1.20.1 ships
     * authlib 6, 1.21.11 ships authlib 7), so no build-time mapping can hide it -
     * the accessor is resolved once at class-init against whatever authlib is
     * actually on the classpath.
     */
    public static String nameOf(PlayerListEntry info) {
        if (info == null || PROFILE_NAME == null) {
            return null;
        }
        try {
            return (String) PROFILE_NAME.invoke(info.getProfile());
        } catch (Throwable ignored) {
            return null;  // no tag this frame; a tab list is not worth a crash
        }
    }

    /** {@code name()} on authlib 7+, {@code getName()} on 6.x. Null if neither. */
    private static final Method PROFILE_NAME = resolveProfileName();

    private static Method resolveProfileName() {
        for (String candidate : new String[]{"name", "getName"}) {
            try {
                Method method = com.mojang.authlib.GameProfile.class
                        .getMethod(candidate);
                if (method.getReturnType() == String.class) {
                    return method;
                }
            } catch (NoSuchMethodException ignored) {
                // wrong authlib generation; try the next spelling
            }
        }
        return null;
    }

    /**
     * The tab-list name for one row, tagged if the player is a Cubeon account.
     * Always returns a name to draw; anything that goes wrong returns the
     * original component unchanged.
     */
    public static Text decorate(String minecraftName, Text displayed) {
        if (displayed == null || minecraftName == null || minecraftName.isEmpty()) {
            return displayed;
        }
        try {
            if (!names().contains(minecraftName)) {
                return displayed;
            }
            return Text.empty()
                    .append(Text.literal("[Cubeon]").setStyle(cubeonGreen()))
                    .append(displayed);
        } catch (Throwable ignored) {
            // getPlayerName is per-row per-frame: anything thrown here is a
            // crash-on-every-frame, not a one-off. An untagged row is free.
            return displayed;
        }
    }

    /** The exact Cubeon green as a Style. */
    private static Style cubeonGreen() {
        return Style.EMPTY.withColor(CUBEON_GREEN);
    }

    /** The Cubeon names this machine knows, rebuilt only when the bridge moves. */
    private static Set<String> names() {
        Bridge bridge = Bridge.get();
        long revision = bridge.revision();
        long playersRevision = bridge.playersRevision();
        if (revision != knownRevision || playersRevision != knownPlayersRevision) {
            Set<String> fresh = BadgeNames.from(bridge.snapshot(), bridge.players());
            // Revision first would leave a window where another thread sees the
            // new revision with the old set; this order can only ever repeat the
            // rebuild, never skip it.
            known = fresh;
            knownRevision = revision;
            knownPlayersRevision = playersRevision;
        }
        return known;
    }
}
