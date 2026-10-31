package com.cubeon.client.cosmetics;

import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.MinecraftClient;
import net.minecraft.entity.player.PlayerEntity;
import java.util.WeakHashMap;

/** Native player identity, visibility and individual animation trackers. */
public final class CosmeticPlayers {
    private static final WeakHashMap<PlayerEntity, CosmeticAnimation.Tracker> MOTION = new WeakHashMap<>();
    private static Object world;
    private CosmeticPlayers() { }
    public static CosmeticView view(int id, float age, boolean gliding) {
        MinecraftClient client = MinecraftClient.getInstance();
        if (client == null || client.world == null) return null;
        var entity = client.world.getEntityById(id);
        return entity instanceof PlayerEntity player ? view(player, age, gliding) : null;
    }
    public static CosmeticView view(PlayerEntity player, float age, boolean gliding) {
        MinecraftClient client = MinecraftClient.getInstance();
        if (client == null || client.player == null || client.world == null) return null;
        var config = CubeonHudConfig.get();
        RemoteCosmetics.context(client.world, config.showOtherCosmetics);
        if (world != client.world) { world = client.world; MOTION.clear(); }
        boolean local = player == client.player;
        if (player.isInvisible() || player.isSpectator()
                || !local && (!config.showOtherCosmetics || player.squaredDistanceTo(client.player) > 4096)) return null;
        CosmeticSelection.Items items = local ? CosmeticSelection.snapshot()
                : RemoteCosmetics.get(player.getName().getString());
        if (items.back() == null && items.shoulder() == null) return null;
        var motion = MOTION.computeIfAbsent(player, ignored -> new CosmeticAnimation.Tracker());
        CosmeticAnimation.Frame frame = config.cosmeticAnimations
                ? motion.sample(age, (float) player.getVelocity().horizontalLength() * 4,
                    gliding, player.isSprinting(), local
                        ? WingAction.INSTANCE.elapsed(client.player, client.world, age) : -1f)
                : motion.disabled();
        return new CosmeticView(items, frame);
    }
}
