package com.cubeon.client.hud;

import java.util.IdentityHashMap;
import java.util.Map;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.font.TextRenderer;
import net.minecraft.client.render.command.OrderedRenderCommandQueue;
import net.minecraft.client.render.entity.state.LivingEntityRenderState;
import net.minecraft.client.render.state.CameraRenderState;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.entity.LivingEntity;
import net.minecraft.entity.mob.Monster;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.scoreboard.AbstractTeam;
import net.minecraft.text.MutableText;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;
import net.minecraft.util.math.Vec3d;

/**
 * 1.21.11 health labels submitted with the entity's own render commands.
 *
 * The HUD projector is mathematically correct, but Minecraft can pipeline the
 * rendered world and later GUI extraction independently. A fast camera turn
 * can therefore expose one old world frame beneath a new HUD label. Keeping
 * this label beside the entity gives both the same camera state and frame.
 */
public final class EnemyHealthWorldLabels {
    private record Label(int hearts, Text mobName) {}

    private static final Map<LivingEntityRenderState, Label> LABELS = new IdentityHashMap<>();
    private static long frame = Long.MIN_VALUE;
    private static int drawn;

    private EnemyHealthWorldLabels() {}

    public static void capture(LivingEntity entity, LivingEntityRenderState state) {
        EnemyHealthFrame.enableWorldLabels();
        syncFrame();
        LABELS.remove(state);

        var client = MinecraftClient.getInstance();
        var player = client.player;
        if (!CubeonHudConfig.get().showEnemyHealth || player == null || client.world == null
                || client.currentScreen != null || client.options.hudHidden
                || entity == player || !(entity instanceof PlayerEntity || entity instanceof Monster)
                || !entity.isAlive() || entity.isSpectator() || entity.isInvisible()
                || entity.isSneaking() || player.isTeammate(entity)
                || player.squaredDistanceTo(entity) > EnemyHealthBar.RANGE * EnemyHealthBar.RANGE) {
            return;
        }
        if (entity instanceof PlayerEntity && entity.getScoreboardTeam() != null) {
            var visibility = entity.getScoreboardTeam().getNameTagVisibilityRule();
            if (visibility == AbstractTeam.VisibilityRule.NEVER
                    || visibility == AbstractTeam.VisibilityRule.HIDE_FOR_OTHER_TEAMS) {
                return;
            }
        }

        Text mobName = entity instanceof Monster && state.displayName == null ? entity.getName() : null;
        LABELS.put(state, new Label(EnemyHealthBar.heartValue(entity.getHealth()), mobName));
    }

    public static void render(LivingEntityRenderState state, MatrixStack matrices,
                              OrderedRenderCommandQueue queue, CameraRenderState camera) {
        syncFrame();
        Label label = LABELS.remove(state);
        if (label == null || drawn >= EnemyHealthBar.MAX_BARS) return;
        drawn++;

        Vec3d position = state.nameLabelPos != null
                ? state.nameLabelPos : new Vec3d(0, state.height, 0);
        matrices.push();
        matrices.translate(position.x, position.y + 0.5, position.z);
        matrices.multiply(camera.orientation);
        matrices.scale(0.025F, -0.025F, 0.025F);

        if (label.mobName != null) {
            submit(queue, matrices, label.mobName, 0, state.light);
        }
        MutableText health = Text.literal("\u2665 ").formatted(Formatting.RED)
                .append(Text.literal(Integer.toString(label.hearts)).formatted(Formatting.WHITE));
        submit(queue, matrices, health, 10, state.light);
        matrices.pop();
    }

    private static void submit(OrderedRenderCommandQueue queue, MatrixStack matrices,
                               Text text, int y, int light) {
        var client = MinecraftClient.getInstance();
        TextRenderer renderer = client.textRenderer;
        queue.submitText(matrices, -renderer.getWidth(text) / 2.0F, y, text.asOrderedText(), true,
                TextRenderer.TextLayerType.NORMAL, light, 0xFFFFFFFF, 0, 0);
    }

    private static void syncFrame() {
        long current = EnemyHealthFrame.current();
        if (frame == current) return;
        frame = current;
        LABELS.clear();
        drawn = 0;
    }
}
