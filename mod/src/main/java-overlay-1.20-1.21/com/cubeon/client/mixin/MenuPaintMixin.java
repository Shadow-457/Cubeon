package com.cubeon.client.mixin;

import com.cubeon.client.MenuPaintImpl;
import com.cubeon.client.ModuleMenuScreen;

import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.screens.Screen;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Hands the mod menu its graphics object, then lets it paint itself - the
 * 1.20-1.21 half.
 *
 * <p>Everything here is written against what the GAME LOG actually said, after
 * three reports in a row were misdiagnosed. Both of these cost a wasted build
 * cycle, so the reasons are recorded rather than tidied away:
 *
 * <p><b>It mixes into {@link Screen}, not {@code ModuleMenuScreen}.</b> The draw
 * call is declared on {@code Screen}; {@code ModuleMenuScreen} only INHERITS
 * it, and Mixin resolves an {@code @Inject} against the target's OWN methods.
 * Aiming at the menu found nothing and, being {@code require = 0}, failed in
 * silence. The instance check keeps it a no-op for every other screen.
 *
 * <p><b>It must NOT extend Screen.</b> A mixin may not have its own target as a
 * superclass. The log rejected it outright: "Super class 'class_437' of
 * MenuPaintMixin was not found in the hierarchy of target class 'class_437'".
 * {@code PauseScreenMixin} can extend Screen because its target is
 * PauseScreen, whose STRICT superclass Screen is genuinely in the hierarchy.
 * Copying that shape here is what broke it.
 *
 * <p><b>There is deliberately no background injection.</b> Cancelling
 * {@code renderBackground} for a see-through menu looked right on 1.20.1, whose
 * signature is {@code (GuiGraphics)}, but 1.21 changed it to
 * {@code (GuiGraphics, int, int, float)} - WITHIN this bracket. A wrong
 * descriptor there failed the WHOLE mixin, so the panel stopped drawing
 * altogether. Reinstating it needs a descriptor that is valid at both ends of
 * the bracket, or a separate mixin per version; neither exists yet. The panel
 * is opaque in the meantime.
 */
@Mixin(Screen.class)
public abstract class MenuPaintMixin {

    /** Proof, in the game log, that the paint hook actually applied. */
    private static boolean cubeon$paintedOnce;

    @Inject(method = "render", at = @At("TAIL"), require = 0)
    private void cubeon$paintMenu(GuiGraphics graphics, int mouseX, int mouseY,
                                  float partialTick, CallbackInfo ci) {
        if (!((Object) this instanceof ModuleMenuScreen)) {
            return;
        }
        if (!cubeon$paintedOnce) {
            cubeon$paintedOnce = true;
            // Proof the injection APPLIED. Three reports were misread as a
            // styling problem because this never ran; one line in the log turns
            // that from a guess into a fact.
            System.err.println("[Cubeon] mod menu paint hook active");
        }
        try {
            ((ModuleMenuScreen) (Object) this)
                    .drawOverlay(new MenuPaintImpl(graphics), mouseX, mouseY);
        } catch (Throwable first) {
            // Fail soft - a throw out of render takes the screen down - but
            // never fail silently.
            com.cubeon.client.MenuPainter.report("paint", first);
        }
    }
}
