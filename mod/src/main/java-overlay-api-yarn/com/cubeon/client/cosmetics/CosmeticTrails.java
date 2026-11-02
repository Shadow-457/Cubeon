package com.cubeon.client.cosmetics;

import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.MinecraftClient;
import net.minecraft.block.Blocks;
import net.minecraft.particle.BlockStateParticleEffect;
import net.minecraft.particle.ParticleTypes;

/** Local, bounded decorative particles. Uses the native particle manager's limits. */
public final class CosmeticTrails {
    private static final TrailEmission EMISSION = new TrailEmission();
    private static final BlockStateParticleEffect LEAVES =
            new BlockStateParticleEffect(ParticleTypes.BLOCK, Blocks.OAK_LEAVES.getDefaultState());
    private static final BlockStateParticleEffect STEPS =
            new BlockStateParticleEffect(ParticleTypes.BLOCK, Blocks.COARSE_DIRT.getDefaultState());
    private CosmeticTrails() { }

    public static void tick() {
        MinecraftClient client = MinecraftClient.getInstance();
        if (client == null || client.player == null || client.world == null || client.isPaused()
                || !CubeonHudConfig.get().cosmeticAnimations
                || client.player.isInvisible() || client.player.isSpectator()) {
            EMISSION.reset(); return;
        }
        var player = client.player;
        CosmeticSelection.refresh();
        String id = CosmeticSelection.get("trail");
        if (id == null) { EMISSION.reset(); return; }
        if (!EMISSION.step(client.world, id, player.age, player.getX(), player.getY(), player.getZ(),
                player.isOnGround() && !player.isTouchingWater() && !player.isFallFlying())) return;
        boolean leaves = "trail_leaves".equals(id);
        var particle = leaves ? LEAVES : STEPS;
        var velocity = player.getVelocity();
        for (int side = -1; side <= 1; side += 2) {
            client.particleManager.addParticle(particle,
                    player.getX() - velocity.x * 1.5 + side * .12,
                    player.getY() + (leaves ? .35 : .04),
                    player.getZ() - velocity.z * 1.5,
                    side * .015, leaves ? .025 : .008, 0);
        }
    }
}
