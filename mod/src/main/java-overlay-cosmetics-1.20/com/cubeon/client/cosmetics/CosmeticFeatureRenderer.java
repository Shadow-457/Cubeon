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
import org.joml.Matrix3f;
import org.joml.Matrix4f;
import org.joml.Vector3f;

/**
 * Draws the local player's selected cosmetics (1.20 - 1.20.4).
 *
 * <p>The geometry is authored in Minecraft model space with the standing body
 * pivot at {@code (0, 0, 0)}. Applying the body part's pose directly makes the
 * items follow the torso through crouching and swimming. The catalogue's
 * coordinates already belong to this space; no height offset is needed.
 *
 * <p>This era has no render-state object yet, so "is this the local player" is
 * an identity check against {@code MinecraftClient.player}. Normals are
 * transformed by hand because 1.20.5 removed the {@code Matrix3f} overload of
 * {@code VertexConsumer.normal}; doing it manually is what lets this copy stay
 * a single file for all five brackets from 1.20 to 1.20.4.
 *
 * <p>Vertex emission is the one part that genuinely differs between eras:
 * 1.20-1.20.6 still requires an explicit {@code next()} to end a vertex, and
 * 1.21 removed it. That is why there are three copies of this class before
 * 1.21.2 rather than one.
 */
public final class CosmeticFeatureRenderer
        extends FeatureRenderer<PlayerEntity, PlayerEntityModel<PlayerEntity>> {

    @SuppressWarnings({"unchecked", "rawtypes"})
    public CosmeticFeatureRenderer(PlayerEntityRenderer renderer) {
        super((FeatureRendererContext<PlayerEntity, PlayerEntityModel<PlayerEntity>>)
                (Object) renderer);
    }

    private final CosmeticAnimation.PosedQuad posed = new CosmeticAnimation.PosedQuad();
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
            // Back first: a wing should sit behind a shoulder pet if they ever
            // overlap, and drawing in that order keeps the depth buffer honest
            // without a sort.
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
        final CosmeticAnimation.Frame itemAnimation = animation == null ? null : animation.forItem(item);
        Identifier texture = Identifier.of("cubeon-client",
                "textures/cosmetics/" + item.texture);
        VertexConsumer buffer = vertexConsumers.getBuffer(
                RenderLayer.getEntityCutoutNoCull(texture));
        MatrixStack.Entry entry = matrices.peek();
        Matrix4f position = entry.getPositionMatrix();
        Matrix3f normalMatrix = entry.getNormalMatrix();
        Vector3f normal = new Vector3f();

        for (CosmeticGeometry.Quad quad : CosmeticGeometry.quads(
                item, catalog.anchorX(item.slot))) {
            posed.set(quad, itemAnimation);
            normal.set(posed.normalX, posed.normalY, posed.normalZ);
            normalMatrix.transform(normal);
            if (normal.lengthSquared() > 1.0e-8f) {
                normal.normalize();
            }
            for (int i = 0; i < 4; i++) {
                buffer.vertex(position, posed.x[i] / 16.0f, posed.y[i] / 16.0f,
                                posed.z[i] / 16.0f)
                        .color(255, 255, 255, 255)
                        .texture(quad.u[i], quad.v[i])
                        .overlay(OverlayTexture.DEFAULT_UV)
                        .light(light)
                        .normal(normal.x, normal.y, normal.z);
                buffer.next();
            }
        }
    }
}
