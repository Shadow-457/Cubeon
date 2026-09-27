package com.cubeon.client.mixin;

import com.cubeon.client.MenuPaintImpl;
import com.cubeon.client.ModuleMenuScreen;

import net.minecraft.client.gui.GuiGraphicsExtractor;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Hands the mod menu its graphics object, then lets it paint itself - the
 * 26.x half.
 *
 * <p>Shares its FQN with the 1.20-1.21 copy in
 * {@code java-overlay-1.20-1.21}, and exists only because 26.x renamed the
 * screen draw call from {@code render(GuiGraphics, ...)} to
 * {@code extractRenderState(GuiGraphicsExtractor, ...)}. Signatures that
 * unrelated cannot share one injector, so this pair is unavoidable - but
 * everything the menu actually draws lives in the shared {@code MenuPainter}.
 *
 * <p>Fail-soft for the same reason as the HUD: a throw out of a screen's
 * extract step takes the screen down with it. An unpainted menu is ugly; a
 * crashed one is worse.
 */
@Mixin(ModuleMenuScreen.class)
public abstract class MenuPaintMixin {

    @Inject(method = "extractRenderState", at = @At("TAIL"), require = 0)
    private void cubeon$paintMenu(GuiGraphicsExtractor graphics, int mouseX,
                                  int mouseY, float partialTick, CallbackInfo ci) {
        try {
            ((ModuleMenuScreen) (Object) this)
                    .drawOverlay(new MenuPaintImpl(graphics), mouseX, mouseY);
        } catch (Throwable ignored) {
            // See the 1.20-1.21 copy: an unpainted menu still works.
        }
    }
}
