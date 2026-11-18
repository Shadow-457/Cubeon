package com.cubeon.client.mixin;

import com.cubeon.client.ui.StartupUi;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.SplashOverlay;
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
@Mixin(SplashOverlay.class)
public abstract class StartupLoadingMixin {
    @Shadow @Final private boolean reloading;
    @Shadow private float progress;
    @Shadow private long reloadCompleteTime;

    @Redirect(method="render", at=@At(value="INVOKE", target="Ljava/util/function/IntSupplier;getAsInt()I"), require=1)
    private int cubeon$background(IntSupplier original) {
        return reloading ? original.getAsInt() : StartupUi.BACKGROUND;
    }

    @ModifyArgs(method="render", at=@At(value="INVOKE", target="Lnet/minecraft/client/gui/DrawContext;drawTexture(Ljava/util/function/Function;Lnet/minecraft/util/Identifier;IIFFIIIIIII)V"), require=2)
    private void cubeon$hideVanillaLogo(Args args) {
        if (!reloading) { args.set(6, 0); args.set(7, 0); }
    }

    @Inject(method="renderProgressBar", at=@At("HEAD"), cancellable=true, require=1)
    private void cubeon$hideVanillaBar(DrawContext context, int x0, int y0, int x1, int y1, float alpha, CallbackInfo ci) {
        if (!reloading) ci.cancel();
    }

    @Inject(method="render", at=@At("TAIL"), require=1)
    private void cubeon$drawStartup(DrawContext context, int mouseX, int mouseY, float delta, CallbackInfo ci) {
        if (!reloading) StartupUi.draw(context::fill,
                context.getScaledWindowWidth(), context.getScaledWindowHeight(),
                progress, StartupUi.opacity(Util.getMeasuringTimeMs(), reloadCompleteTime));
    }
}
