package com.cubeon.client.hud;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.entity.LivingEntity;
import net.minecraft.entity.mob.Monster;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.util.math.Vec3d;
import net.minecraft.scoreboard.AbstractTeam;
import net.minecraft.util.hit.EntityHitResult;
import java.util.Comparator;
import java.util.function.Function;

/** Health beneath visible enemy name tags; no packets, through-wall labels or self HUD. */
public final class EnemyHealthRenderer {
    private EnemyHealthRenderer() {}

    public static void render(DrawContext context, MinecraftClient client,
                              Function<Vec3d, Vec3d> project, float tickDelta) {
        if (!CubeonHudConfig.get().showEnemyHealth || client.player == null || client.world == null
                || client.currentScreen != null || client.options.hudHidden) return;
        var player = client.player;
        var enemies = client.world.getEntitiesByClass(LivingEntity.class,
                player.getBoundingBox().expand(EnemyHealthBar.RANGE), entity ->
                        entity != player && (entity instanceof PlayerEntity || entity instanceof Monster)
                        && entity.isAlive() && !entity.isSpectator() && !entity.isInvisible()
                        && !entity.isSneaking() && !player.isTeammate(entity)
                        && player.squaredDistanceTo(entity) <= EnemyHealthBar.RANGE * EnemyHealthBar.RANGE);
        enemies.sort(Comparator.comparingDouble(player::squaredDistanceTo));
        int drawn = 0;
        for (LivingEntity enemy : enemies) {
            if (drawn == EnemyHealthBar.MAX_BARS) break;
            if (enemy instanceof PlayerEntity && enemy.getScoreboardTeam() != null) {
                var visibility = enemy.getScoreboardTeam().getNameTagVisibilityRule();
                if (visibility == AbstractTeam.VisibilityRule.NEVER || visibility == AbstractTeam.VisibilityRule.HIDE_FOR_OTHER_TEAMS) continue;
            }
            if (!player.canSee(enemy)) continue;
            Vec3d anchor = enemy.getLerpedPos(tickDelta).add(0, enemy.getHeight() + 0.5, 0);
            Vec3d name = project.apply(anchor);
            // Vanilla labels are 9 units high at a 0.025 world scale. Anchor below their bottom.
            Vec3d bottom = project.apply(anchor.add(0, -0.225, 0));
            if (name == null || bottom == null || !EnemyHealthBar.onScreen(name.x, name.y, name.z)
                    || !EnemyHealthBar.onScreen(bottom.x, bottom.y, bottom.z)) continue;
            int center = EnemyHealthBar.screenX(name.x, context.getScaledWindowWidth());
            int y = EnemyHealthBar.screenY(bottom.y, context.getScaledWindowHeight()) + 2;
            int x = center - EnemyHealthBar.WIDTH / 2;
            if (x < 0 || x + EnemyHealthBar.WIDTH > context.getScaledWindowWidth()
                    || y + EnemyHealthBar.HEIGHT > context.getScaledWindowHeight()) continue;
            // Add a mob name only when vanilla has no visible tag for it.
            if (!(enemy instanceof PlayerEntity) && (!enemy.hasCustomName()
                    || (!enemy.isCustomNameVisible() && !(client.crosshairTarget instanceof EntityHitResult hit
                    && hit.getEntity() == enemy)))) {
                var label = enemy.getName();
                context.drawTextWithShadow(client.textRenderer, label,
                        center - client.textRenderer.getWidth(label) / 2,
                        y - client.textRenderer.fontHeight - 2, 0xFFE4E7EB);
            }
            float fraction = EnemyHealthBar.fraction(enemy.getHealth(), enemy.getMaxHealth());
            context.fill(x, y, x + EnemyHealthBar.WIDTH, y + EnemyHealthBar.HEIGHT, EnemyHealthBar.BACKGROUND);
            int fill = Math.round((EnemyHealthBar.WIDTH - 2) * fraction);
            if (fill > 0) context.fill(x + 1, y + 1, x + 1 + fill, y + EnemyHealthBar.HEIGHT - 1,
                    EnemyHealthBar.color(fraction));
            drawn++;
        }
    }
}
