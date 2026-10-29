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
import org.joml.Vector3f;
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
        var down = new Vector3f(0, -EnemyHealthBar.NAME_WORLD_HEIGHT, 0)
                .rotate(client.gameRenderer.getCamera().getRotation());
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
            // Sample camera-facing label height, including when looking up/down.
            Vec3d bottom = project.apply(anchor.add(down.x, down.y, down.z));
            if (name == null || bottom == null || !EnemyHealthBar.onScreen(name.x, name.y, name.z)
                    || !EnemyHealthBar.onScreen(bottom.x, bottom.y, bottom.z)) continue;
            float scale = EnemyHealthBar.labelScale(name.y, bottom.y, context.getScaledWindowHeight());
            if (!Float.isFinite(scale) || scale <= 0) continue;
            int width = Math.max(2, Math.round(EnemyHealthBar.WIDTH * scale));
            int height = Math.max(1, Math.round(EnemyHealthBar.HEIGHT * scale));
            int center = EnemyHealthBar.screenX(name.x, context.getScaledWindowWidth());
            int y = EnemyHealthBar.screenY(name.y, context.getScaledWindowHeight())
                    + Math.round((EnemyHealthBar.NAME_HEIGHT + 2) * scale);
            int x = center - width / 2;
            if (x < 0 || x + width > context.getScaledWindowWidth()
                    || y + height > context.getScaledWindowHeight()) continue;
            // Add a mob name only when vanilla has no visible tag for it.
            if (!(enemy instanceof PlayerEntity) && (!enemy.hasCustomName()
                    || (!enemy.isCustomNameVisible() && !(client.crosshairTarget instanceof EntityHitResult hit
                    && hit.getEntity() == enemy)))) {
                var label = enemy.getName();
                CubeonHud.drawEnemyName(context, client, label, center,
                        EnemyHealthBar.screenY(name.y, context.getScaledWindowHeight()), scale);
            }
            float fraction = EnemyHealthBar.fraction(enemy.getHealth(), enemy.getMaxHealth());
            context.fill(x, y, x + width, y + height, EnemyHealthBar.BACKGROUND);
            int inset = height >= 3 && width >= 4 ? Math.max(1, Math.round(scale)) : 0;
            inset = Math.min(inset, (height - 1) / 2);
            int fill = Math.round((width - 2 * inset) * fraction);
            if (fill > 0) context.fill(x + inset, y + inset, x + inset + fill, y + height - inset,
                    EnemyHealthBar.color(fraction));
            drawn++;
        }
    }
}
