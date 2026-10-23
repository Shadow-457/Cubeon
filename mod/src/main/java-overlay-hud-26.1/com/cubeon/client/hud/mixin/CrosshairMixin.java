package com.cubeon.client.hud.mixin;

import com.cubeon.client.hud.CrosshairScale;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.Gui;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import org.joml.Matrix3x2fStack;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Scales the vanilla crosshair around the centre of the screen while it is over
 * an entity (2026-10-24).
 *
 * <p>26.1 renamed the HUD class to {@code Gui} and changed the HUD to extract a
 * render state through {@code GuiGraphicsExtractor} instead of drawing
 * immediately, but the crosshair is still extracted at the centre of the GUI
 * through the extractor's pose stack, so wrapping the extraction with a pushed
 * scale transform is still enough. {@code extractCrosshair} is the 26.1 name of
 * the 1.21.x {@code renderCrosshair}.
 */
@Mixin(Gui.class)
public class CrosshairMixin {
	/** Set at HEAD when this frame pushed a transform, cleared at RETURN. */
	private static Matrix3x2fStack cubeon$pose;

	@Inject(method = "extractCrosshair", at = @At("HEAD"))
	private void cubeon$scaleCrosshair(GuiGraphicsExtractor graphics, CallbackInfo ci) {
		if (!CubeonHudConfig.get().dynamicCrosshair) {
			CrosshairScale.reset();
			return;
		}

		float scale = CrosshairScale.update(Minecraft.getInstance().crosshairPickEntity != null);

		if (scale <= CrosshairScale.IDLE) {
			return;
		}

		Matrix3x2fStack pose = graphics.pose();
		float centerX = graphics.guiWidth() / 2.0F;
		float centerY = graphics.guiHeight() / 2.0F;

		pose.pushMatrix();
		pose.translate(centerX, centerY);
		pose.scale(scale, scale);
		pose.translate(-centerX, -centerY);

		cubeon$pose = pose;
	}

	@Inject(method = "extractCrosshair", at = @At("RETURN"))
	private void cubeon$restoreCrosshair(CallbackInfo ci) {
		if (cubeon$pose != null) {
			cubeon$pose.popMatrix();
			cubeon$pose = null;
		}
	}
}
