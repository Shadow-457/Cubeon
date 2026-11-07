package com.cubeon.client.hud;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.scores.Team;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.phys.Vec3;
import java.util.Comparator;
import org.joml.Vector3f;

/** Health beneath visible enemy name tags, using only ordinary client entity data. */
public final class EnemyHealthRenderer {
    private EnemyHealthRenderer() {}

    public static void render(GuiGraphicsExtractor graphics, Minecraft client, float partialTick, boolean visible,
                              org.joml.Quaternionfc cameraRotation, Vec3 camera) {
        // The era-specific HUD owns menu/F1 APIs (these moved into Gui/Hud in 26.2).
        if (!visible || !CubeonHudConfig.get().showEnemyHealth || client.player == null || client.level == null) return;
        var player = client.player;
        var enemies = client.level.getEntitiesOfClass(LivingEntity.class,
                player.getBoundingBox().inflate(EnemyHealthBar.RANGE), entity ->
                        entity != player && (entity instanceof Player || entity instanceof Enemy)
                        && entity.isAlive() && !entity.isSpectator() && !entity.isInvisible()
                        && !entity.isShiftKeyDown() && !player.isAlliedTo(entity)
                        && player.distanceToSqr(entity) <= EnemyHealthBar.RANGE * EnemyHealthBar.RANGE);
        enemies.sort(Comparator.comparingDouble(player::distanceToSqr));
        var down = new Vector3f(0, -EnemyHealthBar.NAME_WORLD_HEIGHT, 0)
                .rotate(cameraRotation);
        var right = new Vector3f(EnemyHealthBar.WIDTH * 0.025F / 2, 0, 0).rotate(cameraRotation);
        EnemyHealthBar.Fill fill = (x, y, x2, y2, color) -> CubeonHud.fillEnemyRect(graphics, x, y, x2, y2, color);
        int drawn = 0;
        for (LivingEntity enemy : enemies) {
            if (drawn == EnemyHealthBar.MAX_BARS) break;
            if (enemy instanceof Player && enemy.getTeam() != null) {
                var visibility = enemy.getTeam().getNameTagVisibility();
                if (visibility == Team.Visibility.NEVER || visibility == Team.Visibility.HIDE_FOR_OTHER_TEAMS) continue;
            }
            // Match vanilla's rendered entity interpolation, not physics/tick history.
            Vec3 anchor = new Vec3(
                    EnemyHealthBar.lerp(enemy.xOld, enemy.getX(), partialTick),
                    EnemyHealthBar.lerp(enemy.yOld, enemy.getY(), partialTick) + enemy.getBbHeight() + 0.5,
                    EnemyHealthBar.lerp(enemy.zOld, enemy.getZ(), partialTick));
            Vec3 eye = anchor.add(0, enemy.getEyeHeight() - enemy.getBbHeight() - 0.5, 0);
            float barOffset = (EnemyHealthBar.NAME_HEIGHT + 2 + EnemyHealthBar.HEIGHT / 2F) / EnemyHealthBar.NAME_HEIGHT;
            Vec3 bar = anchor.add(down.x * barOffset, down.y * barOffset, down.z * barOffset);
            if (!visible(client, camera, eye) || !visible(client, camera, bar)
                    || !visible(client, camera, bar.add(right.x, right.y, right.z))
                    || !visible(client, camera, bar.add(-right.x, -right.y, -right.z))) continue;
            var name = client.gameRenderer.projectPointToScreen(anchor);
            var bottom = client.gameRenderer.projectPointToScreen(anchor.add(down.x, down.y, down.z));
            if (!EnemyHealthBar.onScreen(name.x, name.y, name.z)
                    || !EnemyHealthBar.onScreen(bottom.x, bottom.y, bottom.z)) continue;
            float scale = EnemyHealthBar.labelScale(name.y, bottom.y, graphics.guiHeight());
            if (!Float.isFinite(scale) || scale <= 0) continue;
            float width = Math.max(2, EnemyHealthBar.WIDTH * scale);
            float height = Math.max(1, EnemyHealthBar.HEIGHT * scale);
            float center = EnemyHealthBar.preciseScreenX(name.x, graphics.guiWidth());
            float nameY = EnemyHealthBar.preciseScreenY(name.y, graphics.guiHeight());
            float y = nameY + (EnemyHealthBar.NAME_HEIGHT + 2) * scale;
            float x = center - width / 2;
            if (x < 0 || x + width > graphics.guiWidth()
                    || y + height > graphics.guiHeight()) continue;
            if (!(enemy instanceof Player) && (!enemy.hasCustomName()
                    || (!enemy.isCustomNameVisible() && !(client.hitResult instanceof EntityHitResult hit
                    && hit.getEntity() == enemy)))) {
                var label = enemy.getName();
                CubeonHud.drawEnemyName(graphics, client, label, center,
                        nameY, scale);
            }
            float fraction = EnemyHealthBar.fraction(enemy.getHealth(), enemy.getMaxHealth());
            EnemyHealthBar.draw(fill, center, y, scale, fraction);
            drawn++;
        }
    }

    private static boolean visible(Minecraft client, Vec3 camera, Vec3 point) {
        return client.level.clip(new ClipContext(camera, point,
                ClipContext.Block.VISUAL, ClipContext.Fluid.NONE, client.player))
                .getType() == HitResult.Type.MISS;
    }
}
