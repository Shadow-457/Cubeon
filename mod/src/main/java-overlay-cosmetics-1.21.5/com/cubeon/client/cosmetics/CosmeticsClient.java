package com.cubeon.client.cosmetics;

import net.fabricmc.fabric.api.client.rendering.v1.LivingEntityFeatureRendererRegistrationCallback;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.render.entity.PlayerEntityRenderer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Registers the cosmetic renderer for Minecraft 1.21.5 - 1.21.8. */
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
        net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents.END_CLIENT_TICK
                .register(client -> CosmeticTrails.tick());
        LivingEntityFeatureRendererRegistrationCallback.EVENT.register(
                (entityType, renderer, helper, context) -> {
                    if (renderer instanceof PlayerEntityRenderer) {
                        CosmeticFeatureRenderer cosmetics = new CosmeticFeatureRenderer((PlayerEntityRenderer) renderer);
                        helper.register(cosmetics);
                        if (renderer instanceof com.cubeon.client.mixin.CosmeticLayersAccessor access
                                && CosmeticElytra.order(access.cubeon$getCosmeticLayers(),
                                        cosmetics, net.minecraft.client.render.entity.feature.ElytraFeatureRenderer.class)) {
                            cosmetics.enableElytraReplacement();
                        }
                    }
                });
    }
}
