package com.cubeon.client.cosmetics;

import com.cubeon.client.hud.CubeonHudConfig;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.OverlayTexture;
import net.minecraft.client.render.RenderLayer;
import net.minecraft.client.render.VertexConsumer;
import net.minecraft.client.render.command.OrderedRenderCommandQueue;
import net.minecraft.client.render.entity.PlayerEntityRenderer;
import net.minecraft.client.render.entity.feature.FeatureRenderer;
import net.minecraft.client.render.entity.feature.FeatureRendererContext;
import net.minecraft.client.render.entity.model.PlayerEntityModel;
import net.minecraft.client.render.entity.state.PlayerEntityRenderState;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.util.Identifier;

/**
 * Draws selected local and opted-in peer cosmetics (1.21.9 - 1.21.10).
 *
 * <p>1.21.9 moved entity geometry out of the immediate vertex consumer and into
 * the render command queue: the feature renderer submits a callback and the
 * game runs it later. The callback receives the pose that was current at
 * submission time, so the body transform must still be applied before
 * {@code submitCustom} - which is exactly what {@link #draw} does.
 */
public final class CosmeticFeatureRenderer
        extends FeatureRenderer<PlayerEntityRenderState, PlayerEntityModel> {

    @SuppressWarnings("unchecked")
    public CosmeticFeatureRenderer(PlayerEntityRenderer renderer) {
        super((FeatureRendererContext<PlayerEntityRenderState, PlayerEntityModel>)
                (Object) renderer);
    }

    private final CosmeticAnimation.PosedQuad posed = new CosmeticAnimation.PosedQuad();

    @Override
    public void render(MatrixStack matrices, OrderedRenderCommandQueue queue,
                       int light, PlayerEntityRenderState state, float limbAngle,
                       float limbDistance) {
        CosmeticView view = CosmeticPlayers.view(state.id, state.age / 20.0f, state.isGliding);
        if (view == null) return;
        draw(matrices, queue, light, view);
    }

    private void draw(MatrixStack matrices, OrderedRenderCommandQueue queue,
                      int light, CosmeticView view) {
        CosmeticCatalog.Catalog catalog = CosmeticCatalog.get();
        if (catalog == null) {
            return;
        }
        matrices.push();
        getContextModel().body.applyTransform(matrices);
        try {
            drawItem(catalog, "back", matrices, queue, light, view);
            drawItem(catalog, "shoulder", matrices, queue, light, view);
        } finally {
            matrices.pop();
        }
    }

    private void drawItem(CosmeticCatalog.Catalog catalog, String slot,
                          MatrixStack matrices, OrderedRenderCommandQueue queue,
                          int light, CosmeticView view) {
        CosmeticCatalog.Item selected = catalog.get(view.items().get(slot));
        final CosmeticCatalog.Item item = selected == null ? null
                : selected.forWingDepth(CubeonHudConfig.get().wingDepth);
        if (item == null) {
            return;
        }
        final CosmeticAnimation.Frame itemAnimation = view.animation() == null ? null : view.animation().forItem(item);
        Identifier texture = Identifier.of("cubeon-client",
                "textures/cosmetics/" + item.texture);
        RenderLayer layer = RenderLayer.getEntityCutoutNoCull(texture);
        queue.submitCustom(matrices, layer, (entry, buffer) -> {

                    for (CosmeticGeometry.Quad quad : CosmeticGeometry.quads(
                    item, catalog.anchorX(item.slot))) {
                        posed.set(quad, itemAnimation);
                for (int i = 0; i < 4; i++) {
                    buffer.vertex(entry, posed.x[i] / 16.0f, posed.y[i] / 16.0f,
                                    posed.z[i] / 16.0f)
                            .color(255, 255, 255, 255)
                            .texture(quad.u[i], quad.v[i])
                            .overlay(OverlayTexture.DEFAULT_UV)
                            .light(light)
                            .normal(entry, posed.normalX, posed.normalY, posed.normalZ);
                }
            }
        });
    }
}
