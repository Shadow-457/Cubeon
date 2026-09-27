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
 *
 * <p>It also extends {@link Screen} with the protected constructor, matching
 * the mixins here that demonstrably work - see the 1.20-1.21 sibling for why
 * that shape matters when an injection silently does not apply.
 */
@Mixin(Screen.class)
public abstract class MenuPaintMixin {

    /** Proof, in the game log, that the paint hook actually applied. */
    private static boolean cubeon$paintedOnce;

    @Inject(method = "extractRenderState", at = @At("TAIL"), require = 0)
    private void cubeon$paintMenu(GuiGraphicsExtractor graphics, int mouseX,
                                  int mouseY, float partialTick, CallbackInfo ci) {
        if (!((Object) this instanceof ModuleMenuScreen)) {
            return;
        }
        if (!cubeon$paintedOnce) {
            cubeon$paintedOnce = true;
            System.err.println("[Cubeon] mod menu paint hook active");
        }
        try {
            ((ModuleMenuScreen) (Object) this)
                    .drawOverlay(new MenuPaintImpl(graphics), mouseX, mouseY);
        } catch (Throwable first) {
            // See the 1.20-1.21 copy: fail soft, but say so once.
            com.cubeon.client.MenuPainter.report("paint", first);
        }
    }
}
