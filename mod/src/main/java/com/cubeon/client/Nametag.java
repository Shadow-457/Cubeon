package com.cubeon.client;

import java.util.Set;
import java.util.TreeSet;

import net.minecraft.client.Minecraft;
import net.minecraft.network.chat.Component;

/**
 * Decides whose nametag gets the Cubeon badge, and builds the badged name.
 *
 * <p>The badge - {@code [#]Shadow} - is the one piece of Cubeon that other
 * players' names can carry, and it is what makes a server full of Cubeon players
 * look like one. It is client-side only: your game draws the badge on the Cubeon
 * players you can identify, and a vanilla client sitting next to you sees plain
 * names. Nobody's server has to cooperate, which is the whole point.
 *
 * <p>Who counts as a Cubeon player, in the order it is decided:
 * <ol>
 *   <li>You - this game was launched by Cubeon, so the local player always
 *       qualifies, whatever the launcher's account state is.</li>
 *   <li>Your Cubeon account name and every friend on your roster, as the
 *       launcher bridge reports them ({@link Bridge.Snapshot}). Those are the
 *       names this machine can actually prove are Cubeon accounts.</li>
 * </ol>
 * A stranger running Cubeon is not badged yet - the client has no way to ask
 * "is this name a Cubeon account" for arbitrary players. That arrives with the
 * online-players list; when it does, only {@link #names()} changes.
 *
 * <p><b>This runs once per visible player per frame</b> ({@code getDisplayName}
 * is called from nametag rendering), so nothing here allocates or locks in the
 * common case: the name set is rebuilt only when {@link Bridge#revision()}
 * moves, the set compares case-insensitively so a name lookup needs no
 * {@code toLowerCase} copy, and a non-Cubeon name costs one tree lookup and
 * returns null.
 */
public final class Nametag {

    /** Cached Cubeon names, and the bridge revisions they came from. */
    private static volatile Set<String> known =
            new TreeSet<>(String.CASE_INSENSITIVE_ORDER);
    private static volatile long knownRevision = -1;
    private static volatile long knownPlayersRevision = -1;

    private Nametag() {
    }

    /**
     * The badged nametag for a Cubeon player, or null to leave the name alone.
     *
     * @param player     the player entity, compared by identity against the
     *                   local player - no name lookup, so no risk of recursing
     *                   back into {@code getDisplayName}
     * @param plainName  that player's username
     * @param displayed  the name Minecraft was about to draw (team colours,
     *                   scoreboard styling and all - it is kept, badge in front)
     */
    public static Component decorate(Object player, String plainName, Component displayed) {
        if (displayed == null) {
            return null;
        }
        if (!isCubeon(player, plainName)) {
            return null;
        }
        return Component.empty().append(CornerIcon.badge()).append(displayed);
    }

    private static boolean isCubeon(Object player, String plainName) {
        Minecraft mc = Minecraft.getInstance();
        if (mc != null && player != null && mc.player == player) {
            return true;
        }
        if (plainName == null || plainName.isEmpty()) {
            return false;
        }
        return names().contains(plainName);
    }

    /** The Cubeon names this machine knows, rebuilt only when the bridge moves. */
    private static Set<String> names() {
        Bridge bridge = Bridge.get();
        long revision = bridge.revision();
        long playersRevision = bridge.playersRevision();
        if (revision != knownRevision || playersRevision != knownPlayersRevision) {
            Bridge.Snapshot snapshot = bridge.snapshot();
            Set<String> fresh = new TreeSet<>(String.CASE_INSENSITIVE_ORDER);
            add(fresh, snapshot.you());
            for (Bridge.Friend friend : snapshot.friends()) {
                add(fresh, friend.name());
            }
            // The launcher's /players list: every name the account layer can
            // vouch for, so a Cubeon stranger standing next to you in a world
            // is badged too once the launcher knows them.
            for (Bridge.CubeonPlayer player : bridge.players()) {
                add(fresh, player.name());
            }
            // Revision first would leave a window where another thread sees the
            // new revision with the old set; this order can only ever repeat the
            // rebuild, never skip it.
            known = fresh;
            knownRevision = revision;
            knownPlayersRevision = playersRevision;
        }
        return known;
    }

    private static void add(Set<String> into, String name) {
        if (name != null && !name.isEmpty()) {
            into.add(name);
        }
    }
}
