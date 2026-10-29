package com.cubeon.client.cosmetics;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.OverlayTexture;
import net.minecraft.client.render.RenderLayer;
import net.minecraft.client.render.VertexConsumer;
import net.minecraft.client.render.VertexConsumerProvider;
import net.minecraft.client.render.entity.PlayerEntityRenderer;
import net.minecraft.client.render.entity.feature.FeatureRenderer;
import net.minecraft.client.render.entity.feature.FeatureRendererContext;
import net.minecraft.client.render.entity.model.PlayerEntityModel;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.util.Identifier;

/**
 * Draws the local player's selected cosmetics (1.21 - 1.21.1).
 *
 * <p>Minecraft 1.21 removed {@code VertexConsumer.next()}: each {@code vertex}
 * call now ends the previous vertex by itself. Everything else is the 1.20.5
 * copy, because the render-state split did not arrive until 1.21.2.
 */
public final class CosmeticFeatureRenderer
        extends FeatureRenderer<PlayerEntity, PlayerEntityModel<PlayerEntity>> {

    @SuppressWarnings({"unchecked", "rawtypes"})
    public CosmeticFeatureRenderer(PlayerEntityRenderer renderer) {
        super((FeatureRendererContext<PlayerEntity, PlayerEntityModel<PlayerEntity>>)
                (Object) renderer);
    }

    @Override
    public void render(MatrixStack matrices, VertexConsumerProvider vertexConsumers,
                       int light, PlayerEntity entity, float limbAngle,
                       float limbDistance, float tickDelta, float animationProgress,
                       float headYaw, float headPitch) {
        MinecraftClient client = MinecraftClient.getInstance();
        if (client == null || client.player == null || entity != client.player) {
            return;
        }
        draw(matrices, vertexConsumers, light);
    }

    private void draw(MatrixStack matrices, VertexConsumerProvider vertexConsumers,
                      int light) {
        CosmeticCatalog.Catalog catalog = CosmeticCatalog.get();
        if (catalog == null) {
            return;
        }
        CosmeticSelection.refresh();
        matrices.push();
        getContextModel().body.rotate(matrices);
        try {
            drawItem(catalog, "back", matrices, vertexConsumers, light);
            drawItem(catalog, "shoulder", matrices, vertexConsumers, light);
        } finally {
            matrices.pop();
        }
    }

    private void drawItem(CosmeticCatalog.Catalog catalog, String slot,
                          MatrixStack matrices, VertexConsumerProvider vertexConsumers,
                          int light) {
        CosmeticCatalog.Item item = catalog.get(CosmeticSelection.get(slot));
        if (item == null) {
            return;
        }
        Identifier texture = Identifier.of("cubeon-client",
                "textures/cosmetics/" + item.texture);
        VertexConsumer buffer = vertexConsumers.getBuffer(
                RenderLayer.getEntityCutoutNoCull(texture));
        MatrixStack.Entry entry = matrices.peek();
        for (CosmeticGeometry.Quad quad : CosmeticGeometry.quads(
                item, catalog.anchorX(item.slot))) {
            for (int i = 0; i < 4; i++) {
                buffer.vertex(entry, quad.x[i] / 16.0f, quad.y[i] / 16.0f,
                                quad.z[i] / 16.0f)
                        .color(255, 255, 255, 255)
                        .texture(quad.u[i], quad.v[i])
                        .overlay(OverlayTexture.DEFAULT_UV)
                        .light(light)
                        .normal(entry, quad.normalX, quad.normalY, quad.normalZ);
            }
        }
    }
}
