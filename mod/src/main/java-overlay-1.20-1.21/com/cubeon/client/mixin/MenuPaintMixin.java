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
 * <p><b>This mixes into {@link Screen}, not {@code ModuleMenuScreen}, and that
 * is not a stylistic choice.</b> The screen draw call is declared on
 * {@code Screen}, and {@code ModuleMenuScreen} only INHERITS it. Mixin resolves
 * an {@code @Inject} against the methods the target class itself declares, so
 * {@code @Mixin(ModuleMenuScreen.class)} + {@code method = "render"} found
 * nothing - and because the injector is {@code require = 0} it failed
 * SILENTLY. The result was a menu that never painted: no panel, no text, just
 * the invisible hit-target buttons rendering empty. Every other mixin in this
 * mod targets a class that really does declare its injected method
 * ({@code Gui.render}, {@code LocalPlayer.tick}, {@code PauseScreen.init}),
 * which is why this one was the only casualty.
 *
 * <p>So the target is {@code Screen} and the first thing the body does is
 * check the instance type - which makes it a no-op for every other screen in
 * the game. That is the standard price of inheriting a method you cannot
 * override in shared source: {@code render} has different signatures in the two
 * eras ({@code GuiGraphics} vs {@code GuiGraphicsExtractor}), so the screen
 * itself cannot declare it once for both.
 *
 * <p><b>It also extends {@link Screen} with the protected constructor</b>,
 * because that is the shape of the mixins here that demonstrably work
 * ({@code PauseScreenMixin}, {@code TitleScreenMixin}). An earlier version
 * declared nothing, and the result was the worst failure mode available: the
 * mixin did not apply, the config's {@code required: false} swallowed it, and
 * all that was on screen was the menu's own invisible buttons rendering with
 * empty labels. No panel, no text, no error anywhere - which read as a
 * styling problem through three separate reports. If a mixin here appears to
 * do nothing, copy the shape of one that works.
 */
@Mixin(Screen.class)
public abstract class MenuPaintMixin extends Screen {

    /** Proof, in the game log, that the paint hook actually applied. */
    private static boolean cubeon$paintedOnce;

    protected MenuPaintMixin() {
        super(net.minecraft.network.chat.Component.empty());
    }

    /**
     * Cancels Minecraft's own screen background so the game shows through.
     *
     * <p>A mod menu is a HUD, not a settings page. The vanilla pass blurs and
     * darkens the world, and it runs BEFORE this class's paint hook, so no
     * colour chosen in {@link MenuPainter} can undo it - the pass itself has
     * to be cancelled. Without this the "transparent" background is still
     * Minecraft's blur, which reads as dark however it is painted over.
     */
    @Inject(method = "renderBackground", at = @At("HEAD"), cancellable = true,
            require = 0)
    private void cubeon$noVanillaBackdrop(GuiGraphics graphics, CallbackInfo ci) {
        ci.cancel();
    }

    @Inject(method = "render", at = @At("TAIL"), require = 0)
    private void cubeon$paintMenu(GuiGraphics graphics, int mouseX, int mouseY,
                                  float partialTick, CallbackInfo ci) {
        if (!((Object) this instanceof ModuleMenuScreen)) {
            return;
        }
        if (!cubeon$paintedOnce) {
            cubeon$paintedOnce = true;
            // Proof the injection APPLIED. Three reports in a row were misread
            // as a styling problem because this never ran at all; one line
            // turns that from a guess into a fact in the game log.
            System.err.println("[Cubeon] mod menu paint hook active");
        }
        try {
            ((ModuleMenuScreen) (Object) this)
                    .drawOverlay(new MenuPaintImpl(graphics), mouseX, mouseY);
        } catch (Throwable first) {
            // Fail soft - a throw out of render takes the screen down - but do
            // NOT fail silently. The first version swallowed this and the only
            // symptom was a blank panel, which is indistinguishable from "the
            // mixin never applied". One line in the log settles it.
            com.cubeon.client.MenuPainter.report("paint", first);
        }
    }
}
