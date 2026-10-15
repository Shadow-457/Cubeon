package com.cubeon.client;

import java.lang.reflect.Method;
import java.util.Set;
import java.util.TreeSet;

import net.minecraft.client.multiplayer.PlayerInfo;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.Style;
import net.minecraft.network.chat.TextColor;

/**
 * Tags Cubeon players in the TAB LIST, so a friend reads as
 * {@code [Cubeon]Shadow} in green instead of a bare name.
 *
 * <p><b>Tab list only, on purpose.</b> This is the one place a Cubeon marker is
 * purely the player's own business: the tab list is rendered on your screen and
 * nobody else's, so you can pick your friends out without the launcher putting
 * its name on anyone in public. The nametag above a player's head was the
 * opposite case - that one <em>is</em> on display to the whole server - and the
 * badge that used to live there was removed for exactly that reason (see
 * {@code Nametag} in git history). Do not move this into the nametag without
 * treating it as a new decision.
 *
 * <p><b>Why {@code getNameForDisplay}.</b> The obvious target, the tab list
 * renderer, is the single most-reshaped piece of client code between the two
 * eras this mod ships for: 1.20-1.21 has {@code render(GuiGraphics, ...)} and
 * 26.x replaced it with {@code extractRenderState(GuiGraphicsExtractor, ...)}.
 * The method that actually builds each row's name did not move - verified
 * against the real jars, both declare
 * {@code public Component getNameForDisplay(PlayerInfo)} - so one injection
 * covers both brackets with no per-version renderer code. Same reasoning that
 * let the old nametag badge hook {@code Player.getDisplayName()} instead.
 *
 * <p><b>Colour is exact, not approximate.</b> {@code Style.withColor(TextColor)}
 * and {@code TextColor.fromRgb(int)} have the same shape in 1.20.1 and 26.1.2
 * (checked in both jars), so the tag is the real Cubeon green {@code #83C13D}
 * in both - not {@code ChatFormatting.GREEN}, whose chat green is a different
 * colour entirely.
 *
 * <p><b>Cost.</b> {@code getNameForDisplay} runs once per row per frame while
 * the tab list is visible, so the name set is rebuilt only when the bridge
 * moves ({@link Bridge#revision()} / {@link Bridge#playersRevision()}), and it
 * is a case-insensitive {@link TreeSet} so a lookup needs no {@code toLowerCase}
 * copy. A non-Cubeon row costs one tree lookup and the name is returned
 * untouched.
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
     * <p><b>Reflection is deliberate and load-bearing here, not laziness.</b> The
     * obvious {@code info.getProfile().getName()} compiles against authlib 6
     * and throws {@link NoSuchMethodError} at runtime on authlib 7, because
     * authlib 7 turned {@code GameProfile} into a record and RENAMED the
     * accessor {@code getName()} -> {@code name()}. That rename lands INSIDE
     * the 1.20-1.21 bracket's own range (1.20.1 ships authlib 6.0.54,
     * 1.21.11 ships 7.0.61), so it is not a between-bracket problem a
     * per-bracket overlay can solve either - and it is exactly the case
     * mod/brackets.json warns about, in the one direction an overlay cannot
     * rescue: "a method that exists in the oldest exists in the newer ones
     * too" is FALSE for {@code getName}. One jar covers that whole range, so
     * the accessor is resolved once at class-init against whatever authlib is
     * actually on the classpath, and the result is cached in a Method.
     *
     * <p>Cost is one cached reflective call per row per frame, against a path
     * that already builds a Component and does a tree lookup - the invoke is
     * not what makes this path slow. If authlib ever has both, the record
     * accessor is preferred.
     */
    public static String nameOf(PlayerInfo info) {
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
     *
     * <p>Always returns a name to draw. When the player is not a Cubeon user -
     * or when anything at all goes wrong - the original component comes back
     * unchanged, so the worst case is an untagged list rather than a crash
     * while holding down TAB.
     *
     * @param minecraftName that row's Minecraft username, or null to leave the
     *                      row alone. Matching is by username only: the relay's
     *                      internal handle is never a name anyone plays under.
     * @param displayed     the name Minecraft was about to draw, with its team
     *                      and scoreboard styling already applied. Kept verbatim
     *                      after the tag, so a server's own colouring still wins
     *                      on the name itself.
     */
    public static Component decorate(String minecraftName, Component displayed) {
        if (displayed == null || minecraftName == null || minecraftName.isEmpty()) {
            return displayed;
        }
        try {
            if (!names().contains(minecraftName)) {
                return displayed;
            }
            return Component.empty()
                    .append(Component.literal("[Cubeon]").withStyle(cubeonGreen()))
                    .append(displayed);
        } catch (Throwable ignored) {
            // getNameForDisplay is per-row per-frame: anything thrown here is
            // a crash-on-every-frame, not a one-off. An untagged row is free.
            return displayed;
        }
    }

    /**
     * The exact Cubeon green as a Style.
     *
     * <p>A method rather than a shared constant purely so the green is spelled
     * in one place; Style is immutable so building it per call costs nothing
     * that matters on this path.
     */
    private static Style cubeonGreen() {
        return Style.EMPTY.withColor(CUBEON_GREEN);
    }

    /** The Cubeon names this machine knows, rebuilt only when the bridge moves. */
    private static Set<String> names() {
        Bridge bridge = Bridge.get();
        long revision = bridge.revision();
        long playersRevision = bridge.playersRevision();
        if (revision != knownRevision || playersRevision != knownPlayersRevision) {
            // BadgeNames owns the matching rule (in-game names are Minecraft
            // usernames, never relay handles) and is unit-tested on a bare JDK.
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
