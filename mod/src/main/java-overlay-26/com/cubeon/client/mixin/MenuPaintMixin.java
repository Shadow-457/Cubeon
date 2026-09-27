package com.cubeon.client.mixin;

import com.cubeon.client.MenuPaintImpl;
import com.cubeon.client.ModuleMenuScreen;

import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.screens.Screen;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Hands the mod menu its graphics object, then lets it paint itself - the
 * 26.x half.
 *
 * <p>Shares its FQN with the 1.20-1.21 copy, and exists only because 26.x
 * renamed the screen draw call from {@code render(GuiGraphics, ...)} to
 * {@code extractRenderState(GuiGraphicsExtractor, ...)}. Signatures that
 * unrelated cannot share one injector.
 *
 * <p><b>It mixes into {@link Screen} for the same reason its sibling does</b>,
 * and it is worth stating plainly because it cost a whole wasted build:
 * {@code ModuleMenuScreen} only INHERITS the draw call, it does not declare
 * it, and Mixin resolves an {@code @Inject} against the target class's own
 * methods. Targeting the screen directly therefore found nothing and, being
 * {@code require = 0}, failed silently - the menu simply never painted. The
 * instance check below is what keeps injecting into every other screen in the
 * game harmless.
 */
@Mixin(Screen.class)
public abstract class MenuPaintMixin {

    @Inject(method = "extractRenderState", at = @At("TAIL"), require = 0)
    private void cubeon$paintMenu(GuiGraphicsExtractor graphics, int mouseX,
                                  int mouseY, float partialTick, CallbackInfo ci) {
        if (!((Object) this instanceof ModuleMenuScreen)) {
            return;
        }
        try {
            ((ModuleMenuScreen) (Object) this)
                    .drawOverlay(new MenuPaintImpl(graphics), mouseX, mouseY);
        } catch (Throwable ignored) {
            // See the 1.20-1.21 copy: an unpainted menu still works.
        }
    }
}
