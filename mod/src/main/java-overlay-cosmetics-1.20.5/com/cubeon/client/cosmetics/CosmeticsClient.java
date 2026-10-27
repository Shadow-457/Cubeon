package com.cubeon.client.cosmetics;

import net.fabricmc.fabric.api.client.rendering.v1.LivingEntityFeatureRendererRegistrationCallback;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.render.entity.PlayerEntityRenderer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Registers the in-game cosmetic renderer for Minecraft 1.20.5 - 1.20.6.
 *
 * <p>Same shape as every other era's copy: bind the launcher's selection file,
 * then add one feature renderer to the player renderer. Only the Minecraft
 * API calls differ between the copies; the catalogue, selection and geometry
 * live once in {@code src/main/java}.
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
        LivingEntityFeatureRendererRegistrationCallback.EVENT.register(
                (entityType, renderer, helper, context) -> {
                    if (renderer instanceof PlayerEntityRenderer) {
                        helper.register(new CosmeticFeatureRenderer(
                                (PlayerEntityRenderer) renderer));
                    }
                });
    }
}
