package com.cubeon.client.cosmetics;

import com.cubeon.client.hud.CubeonHudConfig;

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
 * Draws selected local and opted-in peer cosmetics (1.20.5 - 1.20.6).
 *
 * <p>Identical to the 1.20 copy except for the vertex call: 1.20.5 replaced the
 * {@code Matrix4f}/{@code Matrix3f} overloads with
 * {@code MatrixStack.Entry} ones, so the pose and the normal matrix travel
 * together. {@code next()} is still required on this era.
 */
public final class CosmeticFeatureRenderer
        extends FeatureRenderer<PlayerEntity, PlayerEntityModel<PlayerEntity>> {

    @SuppressWarnings({"unchecked", "rawtypes"})
    public CosmeticFeatureRenderer(PlayerEntityRenderer renderer) {
        super((FeatureRendererContext<PlayerEntity, PlayerEntityModel<PlayerEntity>>)
                (Object) renderer);
    }

    private final CosmeticAnimation.PosedQuad posed = new CosmeticAnimation.PosedQuad();

    @Override
    public void render(MatrixStack matrices, VertexConsumerProvider vertexConsumers,
                       int light, PlayerEntity entity, float limbAngle,
                       float limbDistance, float tickDelta, float animationProgress,
                       float headYaw, float headPitch) {
        CosmeticView view = CosmeticPlayers.view(entity, (entity.age + tickDelta) / 20.0f, entity.isFallFlying());
        if (view == null) return;
        draw(matrices, vertexConsumers, light, view);
    }

    private void draw(MatrixStack matrices, VertexConsumerProvider vertexConsumers,
                      int light, CosmeticView view) {
        CosmeticCatalog.Catalog catalog = CosmeticCatalog.get();
        if (catalog == null) {
            return;
        }
        matrices.push();
        getContextModel().body.rotate(matrices);
        try {
            drawItem(catalog, "back", matrices, vertexConsumers, light, view);
            drawItem(catalog, "shoulder", matrices, vertexConsumers, light, view);
        } finally {
            matrices.pop();
        }
    }

    private void drawItem(CosmeticCatalog.Catalog catalog, String slot,
                          MatrixStack matrices, VertexConsumerProvider vertexConsumers,
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
        VertexConsumer buffer = vertexConsumers.getBuffer(
                RenderLayer.getEntityCutoutNoCull(texture));
        MatrixStack.Entry entry = matrices.peek();

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
                buffer.next();
            }
        }
    }
}
