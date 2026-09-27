package com.cubeon.client.mixin;

import com.cubeon.client.MenuPaintImpl;
import com.cubeon.client.ModuleMenuScreen;

import net.minecraft.client.gui.GuiGraphics;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Hands the mod menu its graphics object, then lets it paint itself - the
 * 1.20-1.21 half.
 *
 * <p>This mixin is the ONLY version-specific part of the menu, and there is a
 * second one in {@code java-overlay-26} under the same FQN, exactly as
 * {@code CornerIcon} and {@code HudMixin} do. It is per-bracket because the
 * screen draw call itself was renamed: here it is
 * {@code Screen.render(GuiGraphics, int, int, float)}, while 26.x has
 * {@code Screen.extractRenderState(GuiGraphicsExtractor, int, int, float)}.
 * Two signatures that unrelated cannot share one injector.
 *
 * <p>Injected at TAIL so it runs after the framework has laid the screen out;
 * the menu's own hit targets are invisible buttons, so painting over them at
 * the end is what puts the picture on top.
 */
@Mixin(ModuleMenuScreen.class)
public abstract class MenuPaintMixin {

    @Inject(method = "render", at = @At("TAIL"), require = 0)
    private void cubeon$paintMenu(GuiGraphics graphics, int mouseX, int mouseY,
                                  float partialTick, CallbackInfo ci) {
        try {
            ((ModuleMenuScreen) (Object) this)
                    .drawOverlay(new MenuPaintImpl(graphics), mouseX, mouseY);
        } catch (Throwable ignored) {
            // An unpainted menu still works - the invisible hit targets and the
            // settings are all still live. It must never be able to break the
            // screen the way a throw out of render would.
        }
    }
}
