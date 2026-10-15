package com.cubeon.client.mixin;

import com.cubeon.client.TabListTag;

import net.minecraft.client.gui.components.PlayerTabOverlay;
import net.minecraft.client.multiplayer.PlayerInfo;
import net.minecraft.network.chat.Component;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * Tags Cubeon players in the tab list: {@code [Cubeon]Shadow}.
 *
 * <p>Why this method and not the renderer: the tab list render path is the most
 * reshaped thing between the two eras this mod ships for - 1.20-1.21 renders
 * with {@code render(GuiGraphics, ...)} while 26.x extracts render state
 * through {@code GuiGraphicsExtractor} - but the method that BUILDS each row's
 * name is identical in both, verified against the real jars:
 * {@code public Component getNameForDisplay(PlayerInfo)}. One injection, both
 * brackets, no per-version renderer code. The reasoning and the jar evidence
 * are written up in {@link TabListTag}.
 *
 * <p>Deliberately NOT the nametag. The tab list is your own screen; a marker
 * over someone else's head is the whole server's, which is why the old badge
 * there was removed. See {@link TabListTag}'s class doc.
 *
 * <p>Fail-soft, twice over: {@code require = 0} so a future version that moves
 * the method loses the tag instead of the game, and the body is wrapped because
 * this runs once per row per frame - a throw here is a crash-on-every-frame.
 * {@link TabListTag#decorate} already swallows everything and returns the
 * original name; the try/catch is the second belt.
 */
@Mixin(PlayerTabOverlay.class)
public abstract class PlayerTabOverlayMixin {

    @Inject(method = "getNameForDisplay", at = @At("RETURN"), cancellable = true, require = 0)
    private void cubeon$tagTabRow(PlayerInfo info, CallbackInfoReturnable<Component> cir) {
        try {
            Component shown = cir.getReturnValue();
            if (info == null || shown == null) {
                return;
            }
            Component tagged = TabListTag.decorate(
                    TabListTag.nameOf(info), shown);
            if (tagged != null && tagged != shown) {
                cir.setReturnValue(tagged);
            }
        } catch (Throwable ignored) {
            // A missing tag is invisible; a throwing tab list is the game.
        }
    }
}
