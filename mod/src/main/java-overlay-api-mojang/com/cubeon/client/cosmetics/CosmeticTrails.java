package com.cubeon.client.cosmetics;

import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.Minecraft;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.core.particles.BlockParticleOption;
import net.minecraft.core.particles.ParticleTypes;

/** Local, bounded decorative particles. Uses the native particle manager's limits. */
public final class CosmeticTrails {
    private static final TrailEmission EMISSION = new TrailEmission();
    private static final BlockParticleOption LEAVES =
            new BlockParticleOption(ParticleTypes.BLOCK, Blocks.OAK_LEAVES.defaultBlockState());
    private static final BlockParticleOption STEPS =
            new BlockParticleOption(ParticleTypes.BLOCK, Blocks.COARSE_DIRT.defaultBlockState());
    private CosmeticTrails() { }

    public static void tick() {
        Minecraft client = Minecraft.getInstance();
        if (client == null || client.player == null || client.level == null || client.isPaused()
                || !CubeonHudConfig.get().cosmeticAnimations
                || client.player.isInvisible() || client.player.isSpectator()) {
            EMISSION.reset(); return;
        }
        var player = client.player;
        CosmeticSelection.refresh();
        String id = CosmeticSelection.get("trail");
        if (id == null) { EMISSION.reset(); return; }
        if (!EMISSION.step(client.level, id, player.tickCount, player.getX(), player.getY(), player.getZ(),
                player.onGround() && !player.isInWater() && !player.isFallFlying())) return;
        boolean leaves = "trail_leaves".equals(id);
        var particle = leaves ? LEAVES : STEPS;
        var velocity = player.getDeltaMovement();
        for (int side = -1; side <= 1; side += 2) {
            client.particleEngine.createParticle(particle,
                    player.getX() - velocity.x * 1.5 + side * .12,
                    player.getY() + (leaves ? .35 : .04),
                    player.getZ() - velocity.z * 1.5,
                    side * .015, leaves ? .025 : .008, 0);
        }
    }
}
