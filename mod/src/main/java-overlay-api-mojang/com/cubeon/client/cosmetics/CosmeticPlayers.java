package com.cubeon.client.cosmetics;

import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.Minecraft;
import net.minecraft.world.entity.player.Player;
import java.util.WeakHashMap;

/** Native player identity, visibility and individual animation trackers. */
public final class CosmeticPlayers {
    private static final WeakHashMap<Player, CosmeticAnimation.Tracker> MOTION = new WeakHashMap<>();
    private static Object world;
    private CosmeticPlayers() { }
    public static CosmeticView view(int id, float age, boolean gliding) {
        Minecraft client = Minecraft.getInstance();
        if (client == null || client.level == null) return null;
        var entity = client.level.getEntity(id);
        return entity instanceof Player player ? view(player, age, gliding) : null;
    }
    public static CosmeticView view(Player player, float age, boolean gliding) {
        Minecraft client = Minecraft.getInstance();
        if (client == null || client.player == null || client.level == null) return null;
        var config = CubeonHudConfig.get();
        RemoteCosmetics.context(client.level, config.showOtherCosmetics);
        if (world != client.level) { world = client.level; MOTION.clear(); }
        boolean local = player == client.player;
        if (player.isInvisible() || player.isSpectator()
                || !local && (!config.showOtherCosmetics || player.distanceToSqr(client.player) > 4096)) return null;
        CosmeticSelection.Items items = local ? CosmeticSelection.snapshot()
                : RemoteCosmetics.get(player.getName().getString());
        if (items.back() == null && items.shoulder() == null) return null;
        var motion = MOTION.computeIfAbsent(player, ignored -> new CosmeticAnimation.Tracker());
        CosmeticAnimation.Frame frame = config.cosmeticAnimations
                ? motion.sample(age, (float) player.getDeltaMovement().horizontalDistance() * 4,
                    gliding, player.isSprinting(), local
                        ? WingAction.INSTANCE.elapsed(client.player, client.level, age) : -1f)
                : motion.disabled();
        return new CosmeticView(items, frame);
    }
}
