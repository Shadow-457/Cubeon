package com.cubeon.client.mixin;

import com.cubeon.client.TabListTag;

import net.minecraft.client.gui.hud.PlayerListHud;
import net.minecraft.client.network.PlayerListEntry;
import net.minecraft.text.Text;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * Tags Cubeon players in the tab list: {@code [Cubeon]Shadow}.
 *
 * <p>Yarn-mapped twin of {@code java-overlay-api-mojang}'s mixin. The target
 * differs in NAME only - Mojang spells the class {@code PlayerTabOverlay} and
 * the method {@code getNameForDisplay}; Yarn spells them {@code PlayerListHud}
 * and {@code getPlayerName}. Neither moved between 1.20 and 1.21.11, which is
 * why one injection still covers this whole family.
 *
 * <p>Fail-soft, twice over: {@code require = 0} so a future version that moves
 * the method loses the tag instead of the game, and the body is wrapped because
 * this runs once per row per frame.
 */
@Mixin(PlayerListHud.class)
public abstract class PlayerTabOverlayMixin {

    @Inject(method = "getPlayerName", at = @At("RETURN"), cancellable = true, require = 0)
    private void cubeon$tagTabRow(PlayerListEntry info, CallbackInfoReturnable<Text> cir) {
        try {
            Text shown = cir.getReturnValue();
            if (info == null || shown == null) {
                return;
            }
            Text tagged = TabListTag.decorate(
                    TabListTag.nameOf(info), shown);
            if (tagged != null && tagged != shown) {
                cir.setReturnValue(tagged);
            }
        } catch (Throwable ignored) {
            // A missing tag is invisible; a throwing tab list is the game.
        }
    }
}
