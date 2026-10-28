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
 * <p>This copy is for 1.20-1.21.1, where {@code getFov} returns a double.
 * 1.21.2 moved it to float, which is the only difference the two overlays
 * carry - hence one class per return type rather than a reflection dance.
 */
@Mixin(GameRenderer.class)
public abstract class ZoomMixin {
	@Inject(method = "getFov", at = @At("RETURN"), cancellable = true)
	private void cubeon$zoomFov(Camera camera, float tickDelta, boolean changingFov,
			CallbackInfoReturnable<Double> cir) {
		float factor = Zoom.fovFactor(CubeonHudKeybinds.zoomActive());

		if (factor != 1.0F) {
			cir.setReturnValue(cir.getReturnValueD() * factor);
		}
	}
}
