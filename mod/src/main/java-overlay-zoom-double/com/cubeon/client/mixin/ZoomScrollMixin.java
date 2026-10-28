package com.cubeon.client.mixin;

import com.cubeon.client.hud.CubeonHudKeybinds;
import com.cubeon.client.hud.Zoom;
import net.minecraft.client.Mouse;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Feeds the mouse wheel into zoom while the hold key is down (2026-10-28).
 *
 * <p>Vanilla would otherwise scroll the hotbar at the same time, so the event
 * is cancelled for that one notch: holding the zoom key means "adjust the
 * zoom", not "change my held item". Screen widgets never reach this method, so
 * normal scrolling everywhere else is untouched.
 */
@Mixin(Mouse.class)
public abstract class ZoomScrollMixin {
	@Inject(method = "onMouseScroll", at = @At("HEAD"), cancellable = true)
	private void cubeon$zoomScroll(long window, double horizontal, double vertical,
			CallbackInfo ci) {
		if (!CubeonHudKeybinds.zoomActive()) {
			return;
		}

		Zoom.onScroll(vertical);
		ci.cancel();
	}
}
