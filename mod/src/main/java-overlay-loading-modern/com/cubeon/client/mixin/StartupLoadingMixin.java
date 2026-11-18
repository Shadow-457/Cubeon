package com.cubeon.client.mixin;

import com.cubeon.client.ui.StartupUi;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.screens.LoadingOverlay;
import net.minecraft.util.Util;
import java.util.function.IntSupplier;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.Redirect;
import org.spongepowered.asm.mixin.injection.ModifyArgs;
import org.spongepowered.asm.mixin.injection.invoke.arg.Args;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Change startup artwork only; vanilla retains reload, error handling and fade timing. */
@Mixin(LoadingOverlay.class)
public abstract class StartupLoadingMixin {
    @Shadow @Final private boolean fadeIn;
    @Shadow private float currentProgress;
    @Shadow private long fadeOutStart;

    @Redirect(method="extractRenderState", at=@At(value="INVOKE", target="Ljava/util/function/IntSupplier;getAsInt()I"), require=1)
    private int cubeon$background(IntSupplier original) {
        return fadeIn ? original.getAsInt() : StartupUi.BACKGROUND;
    }

    @ModifyArgs(method="extractRenderState", at=@At(value="INVOKE", target="Lnet/minecraft/client/gui/GuiGraphicsExtractor;blit(Lcom/mojang/blaze3d/pipeline/RenderPipeline;Lnet/minecraft/resources/Identifier;IIFFIIIIIII)V"), require=2)
    private void cubeon$hideVanillaLogo(Args args) {
        if (!fadeIn) { args.set(6, 0); args.set(7, 0); }
    }

    @Inject(method="extractProgressBar", at=@At("HEAD"), cancellable=true, require=1)
    private void cubeon$hideVanillaBar(GuiGraphicsExtractor context, int x0, int y0, int x1, int y1, float alpha, CallbackInfo ci) {
        if (!fadeIn) ci.cancel();
    }

    @Inject(method="extractRenderState", at=@At("TAIL"), require=1)
    private void cubeon$drawStartup(GuiGraphicsExtractor context, int mouseX, int mouseY, float delta, CallbackInfo ci) {
        if (!fadeIn) StartupUi.draw(context::fill,
                context.guiWidth(), context.guiHeight(),
                currentProgress, StartupUi.opacity(Util.getMillis(), fadeOutStart));
    }
}
