package com.cubeon.client.hud;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.scores.Team;
import net.minecraft.world.phys.EntityHitResult;
import java.util.Comparator;

/** Health beneath visible enemy name tags, using only ordinary client entity data. */
public final class EnemyHealthRenderer {
    private EnemyHealthRenderer() {}

    public static void render(GuiGraphicsExtractor graphics, Minecraft client, float partialTick, boolean visible) {
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
            var bottom = client.gameRenderer.projectPointToScreen(anchor.add(0, -0.225, 0));
            if (!EnemyHealthBar.onScreen(name.x, name.y, name.z)
                    || !EnemyHealthBar.onScreen(bottom.x, bottom.y, bottom.z)) continue;
            int center = EnemyHealthBar.screenX(name.x, graphics.guiWidth());
            int y = EnemyHealthBar.screenY(bottom.y, graphics.guiHeight()) + 2;
            int x = center - EnemyHealthBar.WIDTH / 2;
            if (x < 0 || x + EnemyHealthBar.WIDTH > graphics.guiWidth()
                    || y + EnemyHealthBar.HEIGHT > graphics.guiHeight()) continue;
            if (!(enemy instanceof Player) && (!enemy.hasCustomName()
                    || (!enemy.isCustomNameVisible() && !(client.hitResult instanceof EntityHitResult hit
                    && hit.getEntity() == enemy)))) {
                var label = enemy.getName();
                graphics.text(client.font, label, center - client.font.width(label) / 2,
                        y - client.font.lineHeight - 2, 0xFFE4E7EB, true);
            }
            float fraction = EnemyHealthBar.fraction(enemy.getHealth(), enemy.getMaxHealth());
            graphics.fill(x, y, x + EnemyHealthBar.WIDTH, y + EnemyHealthBar.HEIGHT, EnemyHealthBar.BACKGROUND);
            int fill = Math.round((EnemyHealthBar.WIDTH - 2) * fraction);
            if (fill > 0) graphics.fill(x + 1, y + 1, x + 1 + fill, y + EnemyHealthBar.HEIGHT - 1,
                    EnemyHealthBar.color(fraction));
            drawn++;
        }
    }
}
