package com.cubeon.client.mixin;

import java.util.List;

import com.cubeon.client.modules.HudState;

import net.minecraft.client.DeltaTracker;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.Gui;
import net.minecraft.client.gui.GuiGraphicsExtractor;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Draws the enabled HUD modules, for the 26.x bracket.
 *
 * <p>The 1.20-1.21 copy shares this FQN on purpose - the mixin config names
 * {@code HudMixin} and each bracket compiles in its own copy from
 * {@code src/main/java-overlay-<key>}. The split is forced by the game, not by
 * taste: 26.x replaced the HUD draw call entirely, so this era has
 * {@code extractRenderState(GuiGraphicsExtractor, DeltaTracker)} where 1.20-1.21
 * has {@code render(GuiGraphics, float)}. The signatures are unrelated, so no
 * single injector can serve both.
 *
 * <p>What IS shared is everything that decides the content: {@link
 * HudState#lines()} builds the strings with no reference to how they are
 * drawn, and both copies do nothing but call
 * {@code text(Font, String, x, y, colour, shadow)}.
 *
 * <p>Note this is an <em>extract</em> call, so the coordinates handed to it are
 * in the extractor's own space, not screen space - the same as every other
 * thing the HUD draws here.
 */
@Mixin(Gui.class)
public abstract class HudMixin {

    @Inject(method = "extractRenderState", at = @At("TAIL"), require = 0)
    private void cubeon$drawHud(GuiGraphicsExtractor graphics, DeltaTracker delta,
                                CallbackInfo ci) {
        try {
            List<String> lines = HudState.lines();
            if (lines.isEmpty()) {
                return;
            }
            var font = Minecraft.getInstance().font;
            int y = 4;
            for (String line : lines) {
                graphics.text(font, line, 4, y, 0xFFFFFFFF, true);
                y += 10;
            }
        } catch (Throwable ignored) {
            // A missing HUD line is invisible; a throwing HUD is unplayable.
        }
    }
}
