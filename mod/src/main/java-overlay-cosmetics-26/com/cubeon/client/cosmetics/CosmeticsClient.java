package com.cubeon.client.cosmetics;

import net.fabricmc.fabric.api.client.rendering.v1.LivingEntityRenderLayerRegistrationCallback;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.renderer.entity.player.AvatarRenderer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Registers the cosmetic renderer for Minecraft 26.x.
 *
 * <p>26.x renamed Fabric's registration callback and the layer base class, and
 * ships unobfuscated Mojang names, so this copy is written against
 * {@code RenderLayer.submit} / {@code SubmitNodeCollector}. Checking
 * {@code instanceof AvatarRenderer} rather than the entity type is deliberate:
 * 26.2 moved {@code EntityType.PLAYER} to {@code EntityTypes.PLAYER}, and the
 * renderer identity is both version-stable and exactly what we want.
 */
public final class CosmeticsClient {

    private static final Logger LOGGER = LoggerFactory.getLogger("Cubeon Client");

    private CosmeticsClient() {
    }

    public static void register() {
        CosmeticSelection.bind(FabricLoader.getInstance().getConfigDir()
                .resolve(CosmeticSelection.FILE_NAME));
        if (CosmeticCatalog.get() == null) {
            LOGGER.warn("Cubeon cosmetics catalogue is missing from the jar; "
                    + "cosmetics are disabled.");
            return;
        }
        LivingEntityRenderLayerRegistrationCallback.EVENT.register(
                (entityType, renderer, helper, context) -> {
                    if (renderer instanceof AvatarRenderer) {
                        helper.register(new CosmeticRenderLayer(
                                (AvatarRenderer<?>) renderer));
                    }
                });
    }
}
