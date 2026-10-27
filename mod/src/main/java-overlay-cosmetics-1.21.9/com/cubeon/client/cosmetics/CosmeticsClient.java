package com.cubeon.client.cosmetics;

import net.fabricmc.fabric.api.client.rendering.v1.LivingEntityFeatureRendererRegistrationCallback;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.render.entity.PlayerEntityRenderer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Registers the cosmetic renderer for Minecraft 1.21.9 - 1.21.10. */
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
