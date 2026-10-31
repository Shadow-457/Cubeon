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
 * Draws selected local and opted-in peer cosmetics (26.x).
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

    private final CosmeticAnimation.PosedQuad posed = new CosmeticAnimation.PosedQuad();

    @Override
    public void submit(PoseStack pose, SubmitNodeCollector collector, int light,
                       AvatarRenderState state, float limbAngle, float limbDistance) {
        CosmeticView view = CosmeticPlayers.view(state.id, state.ageInTicks / 20.0f, state.isFallFlying);
        if (view == null) return;
        CosmeticCatalog.Catalog catalog = CosmeticCatalog.get();
        if (catalog == null) return;
        pose.pushPose();
        getParentModel().body.translateAndRotate(pose);
        try {
            drawItem(catalog, "back", pose, collector, light, view);
            drawItem(catalog, "shoulder", pose, collector, light, view);
        } finally {
            pose.popPose();
        }
    }

    private void drawItem(CosmeticCatalog.Catalog catalog, String slot,
                          PoseStack pose, SubmitNodeCollector collector, int light,
                          CosmeticView view) {
        CosmeticCatalog.Item selected = catalog.get(view.items().get(slot));
        final CosmeticCatalog.Item item = selected == null ? null
                : selected.forWingDepth(CubeonHudConfig.get().wingDepth);
        if (item == null) {
            return;
        }
        final CosmeticAnimation.Frame itemAnimation = view.animation() == null ? null : view.animation().forItem(item);
        Identifier texture = Identifier.fromNamespaceAndPath("cubeon-client",
                "textures/cosmetics/" + item.texture);
        RenderType type = RenderTypes.entityCutout(texture, false);
        collector.submitCustomGeometry(pose, type, (entry, buffer) -> {

            for (CosmeticGeometry.Quad quad : CosmeticGeometry.quads(
                    item, catalog.anchorX(item.slot))) {
                posed.set(quad, itemAnimation);
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
