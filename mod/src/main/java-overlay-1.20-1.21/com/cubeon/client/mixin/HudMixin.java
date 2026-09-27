package com.cubeon.client.mixin;

import java.util.List;

import com.cubeon.client.modules.HudState;

import net.minecraft.client.gui.Gui;
import net.minecraft.client.gui.GuiGraphics;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Draws the enabled HUD modules, for the 1.20-1.21 bracket.
 *
 * <p>This is the 26.x copy's counterpart and shares its FQN on purpose: the
 * mixin config names {@code HudMixin}, and each bracket compiles in its own
 * copy from {@code src/main/java-overlay-<key>}. That is the same arrangement
 * {@code CornerIcon} already uses, and for the same reason - the in-game HUD
 * draw call is one of the few things that was genuinely reshaped between the
 * eras (here {@code Gui.render(GuiGraphics, float)}, there
 * {@code Gui.extractRenderState(GuiGraphicsExtractor, DeltaTracker)}), so it
 * cannot be shared even though everything that decides <em>what</em> to draw
 * can.
 *
 * <p>Kept deliberately small: it does no game logic at all, only
 * {@link HudState#lines()} and a stack of drawString calls. Everything about
 * which lines exist and what they say lives in the shared, testable code.
 */
@Mixin(Gui.class)
public abstract class HudMixin {

    @Inject(method = "render", at = @At("TAIL"), require = 0)
    private void cubeon$drawHud(GuiGraphics graphics, float partialTick,
                                CallbackInfo ci) {
        try {
            List<String> lines = HudState.lines();
            if (lines.isEmpty()) {
                return;
            }
            int y = 4;
            for (String line : lines) {
                graphics.drawString(net.minecraft.client.Minecraft.getInstance().font,
                        line, 4, y, 0xFFFFFF, true);
                y += 10;
            }
        } catch (Throwable ignored) {
            // A missing HUD line is invisible; a throwing HUD is unplayable.
        }
    }
}
