package com.cubeon.client.hud;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.entity.LivingEntity;
import net.minecraft.entity.mob.Monster;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.util.math.Vec3d;
import net.minecraft.scoreboard.AbstractTeam;
import net.minecraft.util.hit.EntityHitResult;
import net.minecraft.util.hit.HitResult;
import net.minecraft.world.RaycastContext;
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
        var right = new Vector3f(EnemyHealthBar.WIDTH * 0.025F / 2, 0, 0)
                .rotate(client.gameRenderer.getCamera().getRotation());
        Vec3d camera = HealthCamera.position(client.gameRenderer.getCamera());
        var forward = new Vector3f(0, 0, -1).rotate(client.gameRenderer.getCamera().getRotation());
        EnemyHealthBar.Fill fill = (x, y, x2, y2, color) -> CubeonHud.fillEnemyRect(context, x, y, x2, y2, color);
        int drawn = 0;
        for (LivingEntity enemy : enemies) {
            if (drawn == EnemyHealthBar.MAX_BARS) break;
            if (enemy instanceof PlayerEntity && enemy.getScoreboardTeam() != null) {
                var visibility = enemy.getScoreboardTeam().getNameTagVisibilityRule();
                if (visibility == AbstractTeam.VisibilityRule.NEVER || visibility == AbstractTeam.VisibilityRule.HIDE_FOR_OTHER_TEAMS) continue;
            }
            // Match vanilla's rendered entity interpolation, not physics/tick history.
            Vec3d anchor = new Vec3d(
                    EnemyHealthBar.lerp(enemy.lastRenderX, enemy.getX(), tickDelta),
                    EnemyHealthBar.lerp(enemy.lastRenderY, enemy.getY(), tickDelta) + enemy.getHeight() + 0.5,
                    EnemyHealthBar.lerp(enemy.lastRenderZ, enemy.getZ(), tickDelta));
            if (!EnemyHealthBar.inFront(anchor.x-camera.x, anchor.y-camera.y, anchor.z-camera.z, forward)) continue;
            Vec3d eye = anchor.add(0, enemy.getEyeHeight(enemy.getPose()) - enemy.getHeight() - 0.5, 0);
            float barOffset = (EnemyHealthBar.NAME_HEIGHT + 2 + EnemyHealthBar.HEIGHT / 2F) / EnemyHealthBar.NAME_HEIGHT;
            Vec3d bar = anchor.add(down.x * barOffset, down.y * barOffset, down.z * barOffset);
            Vec3d name = project.apply(anchor);
            // Sample camera-facing label height, including when looking up/down.
            Vec3d bottom = project.apply(anchor.add(down.x, down.y, down.z));
            if (name == null || bottom == null || !EnemyHealthBar.onScreen(name.x, name.y, name.z)
                    || !EnemyHealthBar.onScreen(bottom.x, bottom.y, bottom.z)) continue;
            float scale = EnemyHealthBar.labelScale(name.y, bottom.y, context.getScaledWindowHeight());
            if (!Float.isFinite(scale) || scale <= 0) continue;
            float width = Math.max(2, EnemyHealthBar.WIDTH * scale);
            float height = Math.max(1, EnemyHealthBar.HEIGHT * scale);
            float center = EnemyHealthBar.preciseScreenX(name.x, context.getScaledWindowWidth());
            float nameY = EnemyHealthBar.preciseScreenY(name.y, context.getScaledWindowHeight());
            float y = nameY + (EnemyHealthBar.NAME_HEIGHT + 2) * scale;
            float x = center - width / 2;
            if (x < 0 || x + width > context.getScaledWindowWidth()
                    || y + height > context.getScaledWindowHeight()) continue;
            if (!visible(client, camera, eye) || !visible(client, camera, bar)
                    || !visible(client, camera, bar.add(right.x, right.y, right.z))
                    || !visible(client, camera, bar.add(-right.x, -right.y, -right.z))) continue;
            // Add a mob name only when vanilla has no visible tag for it.
            if (!(enemy instanceof PlayerEntity) && (!enemy.hasCustomName()
                    || (!enemy.isCustomNameVisible() && !(client.crosshairTarget instanceof EntityHitResult hit
                    && hit.getEntity() == enemy)))) {
                var label = enemy.getName();
                CubeonHud.drawEnemyName(context, client, label, center,
                        nameY, scale);
            }
            float fraction = EnemyHealthBar.fraction(enemy.getHealth(), enemy.getMaxHealth());
            EnemyHealthBar.draw(fill, center, y, scale, fraction);
            drawn++;
        }
    }

    private static boolean visible(MinecraftClient client, Vec3d camera, Vec3d point) {
        return client.world.raycast(new RaycastContext(camera, point,
                RaycastContext.ShapeType.VISUAL, RaycastContext.FluidHandling.NONE, client.player))
                .getType() == HitResult.Type.MISS;
    }
}
