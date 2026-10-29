package com.cubeon.client.cosmetics;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.OverlayTexture;
import net.minecraft.client.render.RenderLayers;
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
 * Draws the local player's selected cosmetics (1.21.11).
 *
 * <p>1.21.11 moved the entity render-layer factories off {@code RenderLayer}
 * onto {@code RenderLayers}; the queued submission API is 1.21.9's. That one
 * rename is the whole reason this copy exists.
 */
public final class CosmeticFeatureRenderer
        extends FeatureRenderer<PlayerEntityRenderState, PlayerEntityModel> {

    @SuppressWarnings("unchecked")
    public CosmeticFeatureRenderer(PlayerEntityRenderer renderer) {
        super((FeatureRendererContext<PlayerEntityRenderState, PlayerEntityModel>)
                (Object) renderer);
    }

    @Override
    public void render(MatrixStack matrices, OrderedRenderCommandQueue queue,
                       int light, PlayerEntityRenderState state, float limbAngle,
                       float limbDistance) {
        MinecraftClient client = MinecraftClient.getInstance();
        if (client == null || client.player == null
                || state.id != client.player.getId()) {
            return;
        }
        draw(matrices, queue, light);
    }

    private void draw(MatrixStack matrices, OrderedRenderCommandQueue queue, int light) {
        CosmeticCatalog.Catalog catalog = CosmeticCatalog.get();
        if (catalog == null) {
            return;
        }
        CosmeticSelection.refresh();
        matrices.push();
        getContextModel().body.applyTransform(matrices);
        try {
            drawItem(catalog, "back", matrices, queue, light);
            drawItem(catalog, "shoulder", matrices, queue, light);
        } finally {
            matrices.pop();
        }
    }

    private void drawItem(CosmeticCatalog.Catalog catalog, String slot,
                          MatrixStack matrices, OrderedRenderCommandQueue queue,
                          int light) {
        CosmeticCatalog.Item item = catalog.get(CosmeticSelection.get(slot));
        if (item == null) {
            return;
        }
        Identifier texture = Identifier.of("cubeon-client",
                "textures/cosmetics/" + item.texture);
        queue.submitCustom(matrices, RenderLayers.entityCutoutNoCull(texture),
                (entry, buffer) -> {
                    for (CosmeticGeometry.Quad quad : CosmeticGeometry.quads(
                            item, catalog.anchorX(item.slot))) {
                        for (int i = 0; i < 4; i++) {
                            buffer.vertex(entry, quad.x[i] / 16.0f,
                                            quad.y[i] / 16.0f, quad.z[i] / 16.0f)
                                    .color(255, 255, 255, 255)
                                    .texture(quad.u[i], quad.v[i])
                                    .overlay(OverlayTexture.DEFAULT_UV)
                                    .light(light)
                                    .normal(entry, quad.normalX, quad.normalY,
                                            quad.normalZ);
                        }
                    }
                });
    }
}
