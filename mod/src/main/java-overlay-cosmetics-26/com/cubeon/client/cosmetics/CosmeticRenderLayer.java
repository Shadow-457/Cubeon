package com.cubeon.client.cosmetics;

import com.cubeon.client.hud.CubeonHudConfig;

import com.mojang.blaze3d.vertex.PoseStack;
import com.mojang.blaze3d.vertex.VertexConsumer;
import net.minecraft.client.Minecraft;
import net.minecraft.client.model.player.PlayerModel;
import net.minecraft.client.renderer.SubmitNodeCollector;
import net.minecraft.client.renderer.entity.RenderLayerParent;
import net.minecraft.client.renderer.entity.layers.RenderLayer;
import net.minecraft.client.renderer.entity.state.AvatarRenderState;
import net.minecraft.client.renderer.rendertype.RenderType;
import net.minecraft.client.renderer.rendertype.RenderTypes;
import net.minecraft.client.renderer.texture.OverlayTexture;
import net.minecraft.resources.Identifier;

/**
 * Draws the local player's selected cosmetics (26.x).
 *
 * <p>26.x queues all geometry through {@code SubmitNodeCollector}. The body
 * pose is applied before {@code submitCustomGeometry}, which snapshots it; the
 * callback then emits the same quads the launcher preview draws. The local
 * player is identified by entity id, which 26.x exposes directly on
 * {@code AvatarRenderState}.
 */
public final class CosmeticRenderLayer
        extends RenderLayer<AvatarRenderState, PlayerModel> {

    public CosmeticRenderLayer(RenderLayerParent<AvatarRenderState, PlayerModel> parent) {
        super(parent);
    }

    private final CosmeticAnimation.Tracker motion = new CosmeticAnimation.Tracker();

    @Override
    public void submit(PoseStack pose, SubmitNodeCollector collector, int light,
                       AvatarRenderState state, float limbAngle, float limbDistance) {
        Minecraft client = Minecraft.getInstance();
        if (client == null || client.player == null
                || state.id != client.player.getId()) {
            return;
        }
        CosmeticCatalog.Catalog catalog = CosmeticCatalog.get();
        if (catalog == null) {
            return;
        }
        CosmeticAnimation.Frame animation = CubeonHudConfig.get().cosmeticAnimations
                ? motion.sample(state.ageInTicks / 20.0f,
                (float) client.player.getDeltaMovement().horizontalDistance() * 4, state.isFallFlying, client.player.isSprinting(),
                WingAction.INSTANCE.elapsed(client.player, client.level, state.ageInTicks / 20.0f)) : motion.disabled();
        CosmeticSelection.refresh();
        pose.pushPose();
        getParentModel().body.translateAndRotate(pose);
        try {
            drawItem(catalog, "back", pose, collector, light, animation);
            drawItem(catalog, "shoulder", pose, collector, light, animation);
        } finally {
            pose.popPose();
        }
    }

    private void drawItem(CosmeticCatalog.Catalog catalog, String slot,
                          PoseStack pose, SubmitNodeCollector collector, int light,
                          CosmeticAnimation.Frame animation) {
        CosmeticCatalog.Item item = catalog.get(CosmeticSelection.get(slot));
        if (item == null) {
            return;
        }
        Identifier texture = Identifier.fromNamespaceAndPath("cubeon-client",
                "textures/cosmetics/" + item.texture);
        RenderType type = RenderTypes.entityCutout(texture, false);
        collector.submitCustomGeometry(pose, type, (entry, buffer) -> {
            CosmeticAnimation.PosedQuad posed = new CosmeticAnimation.PosedQuad();
            for (CosmeticGeometry.Quad quad : CosmeticGeometry.quads(
                    item, catalog.anchorX(item.slot))) {
                posed.set(quad, animation);
                for (int i = 0; i < 4; i++) {
                    buffer.addVertex(entry, posed.x[i] / 16.0f, posed.y[i] / 16.0f,
                                    posed.z[i] / 16.0f)
                            .setColor(255, 255, 255, 255)
                            .setUv(quad.u[i], quad.v[i])
                            .setOverlay(OverlayTexture.NO_OVERLAY)
                            .setLight(light)
                            .setNormal(entry, posed.normalX, posed.normalY,
                                    posed.normalZ);
                }
            }
        });
    }
}
