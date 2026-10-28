package com.cubeon.client.mixin;

import com.cubeon.client.hud.CubeonHudKeybinds;
import com.cubeon.client.hud.Zoom;
import net.minecraft.client.render.Camera;
import net.minecraft.client.render.GameRenderer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * Narrows the field of view while the zoom key is held (2026-10-28).
 *
 * <p>This copy is for 1.21.2-1.21.11, where {@code getFov} returns a float.
 * The double-returning copy lives in the zoom-double overlay.
 */
@Mixin(GameRenderer.class)
public abstract class ZoomMixin {
	@Inject(method = "getFov", at = @At("RETURN"), cancellable = true)
	private void cubeon$zoomFov(Camera camera, float tickDelta, boolean changingFov,
			CallbackInfoReturnable<Float> cir) {
		float factor = Zoom.fovFactor(CubeonHudKeybinds.zoomActive());

		if (factor != 1.0F) {
			cir.setReturnValue(cir.getReturnValueF() * factor);
		}
	}
}
