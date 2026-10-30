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
 * Draws the local player's selected cosmetics (1.20.5 - 1.20.6).
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

    private final CosmeticAnimation.Tracker motion = new CosmeticAnimation.Tracker();

    @Override
    public void render(MatrixStack matrices, VertexConsumerProvider vertexConsumers,
                       int light, PlayerEntity entity, float limbAngle,
                       float limbDistance, float tickDelta, float animationProgress,
                       float headYaw, float headPitch) {
        MinecraftClient client = MinecraftClient.getInstance();
        if (client == null || client.player == null || entity != client.player) {
            return;
        }
        CosmeticAnimation.Frame animation = CubeonHudConfig.get().cosmeticAnimations
                ? motion.sample((entity.age + tickDelta) / 20.0f,
                (float) entity.getVelocity().horizontalLength() * 4, entity.isFallFlying(), entity.isSprinting(),
                WingAction.INSTANCE.elapsed(client.player, client.world, (entity.age + tickDelta) / 20.0f)) : motion.disabled();
        draw(matrices, vertexConsumers, light, animation);
    }

    private void draw(MatrixStack matrices, VertexConsumerProvider vertexConsumers,
                      int light, CosmeticAnimation.Frame animation) {
        CosmeticCatalog.Catalog catalog = CosmeticCatalog.get();
        if (catalog == null) {
            return;
        }
        CosmeticSelection.refresh();
        matrices.push();
        getContextModel().body.rotate(matrices);
        try {
            drawItem(catalog, "back", matrices, vertexConsumers, light, animation);
            drawItem(catalog, "shoulder", matrices, vertexConsumers, light, animation);
        } finally {
            matrices.pop();
        }
    }

    private void drawItem(CosmeticCatalog.Catalog catalog, String slot,
                          MatrixStack matrices, VertexConsumerProvider vertexConsumers,
                          int light, CosmeticAnimation.Frame animation) {
        CosmeticCatalog.Item item = catalog.get(CosmeticSelection.get(slot));
        if (item == null) {
            return;
        }
        Identifier texture = Identifier.of("cubeon-client",
                "textures/cosmetics/" + item.texture);
        VertexConsumer buffer = vertexConsumers.getBuffer(
                RenderLayer.getEntityCutoutNoCull(texture));
        MatrixStack.Entry entry = matrices.peek();
        CosmeticAnimation.PosedQuad posed = new CosmeticAnimation.PosedQuad();
        for (CosmeticGeometry.Quad quad : CosmeticGeometry.quads(
                item, catalog.anchorX(item.slot))) {
            posed.set(quad, animation);
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
