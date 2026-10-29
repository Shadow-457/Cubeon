package com.cubeon.client.hud;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.scores.Team;
import net.minecraft.world.phys.EntityHitResult;
import java.util.Comparator;
import org.joml.Vector3f;

/** Health beneath visible enemy name tags, using only ordinary client entity data. */
public final class EnemyHealthRenderer {
    private EnemyHealthRenderer() {}

    public static void render(GuiGraphicsExtractor graphics, Minecraft client, float partialTick, boolean visible, org.joml.Quaternionfc cameraRotation) {
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
        int drawn = 0;
        for (LivingEntity enemy : enemies) {
            if (drawn == EnemyHealthBar.MAX_BARS) break;
            if (enemy instanceof Player && enemy.getTeam() != null) {
                var visibility = enemy.getTeam().getNameTagVisibility();
                if (visibility == Team.Visibility.NEVER || visibility == Team.Visibility.HIDE_FOR_OTHER_TEAMS) continue;
            }
            if (!player.hasLineOfSight(enemy)) continue;
            var anchor = enemy.getPosition(partialTick).add(0, enemy.getBbHeight() + 0.5, 0);
            var name = client.gameRenderer.projectPointToScreen(anchor);
            var bottom = client.gameRenderer.projectPointToScreen(anchor.add(down.x, down.y, down.z));
            if (!EnemyHealthBar.onScreen(name.x, name.y, name.z)
                    || !EnemyHealthBar.onScreen(bottom.x, bottom.y, bottom.z)) continue;
            float scale = EnemyHealthBar.labelScale(name.y, bottom.y, graphics.guiHeight());
            if (!Float.isFinite(scale) || scale <= 0) continue;
            int width = Math.max(2, Math.round(EnemyHealthBar.WIDTH * scale));
            int height = Math.max(1, Math.round(EnemyHealthBar.HEIGHT * scale));
            int center = EnemyHealthBar.screenX(name.x, graphics.guiWidth());
            int y = EnemyHealthBar.screenY(name.y, graphics.guiHeight())
                    + Math.round((EnemyHealthBar.NAME_HEIGHT + 2) * scale);
            int x = center - width / 2;
            if (x < 0 || x + width > graphics.guiWidth()
                    || y + height > graphics.guiHeight()) continue;
            if (!(enemy instanceof Player) && (!enemy.hasCustomName()
                    || (!enemy.isCustomNameVisible() && !(client.hitResult instanceof EntityHitResult hit
                    && hit.getEntity() == enemy)))) {
                var label = enemy.getName();
                CubeonHud.drawEnemyName(graphics, client, label, center,
                        EnemyHealthBar.screenY(name.y, graphics.guiHeight()), scale);
            }
            float fraction = EnemyHealthBar.fraction(enemy.getHealth(), enemy.getMaxHealth());
            graphics.fill(x, y, x + width, y + height, EnemyHealthBar.BACKGROUND);
            int inset = height >= 3 && width >= 4 ? Math.max(1, Math.round(scale)) : 0;
            inset = Math.min(inset, (height - 1) / 2);
            int fill = Math.round((width - 2 * inset) * fraction);
            if (fill > 0) graphics.fill(x + inset, y + inset, x + inset + fill, y + height - inset,
                    EnemyHealthBar.color(fraction));
            drawn++;
        }
    }
}
