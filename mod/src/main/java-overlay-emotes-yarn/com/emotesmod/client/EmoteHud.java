package com.emotesmod.client;

import com.emotesmod.Emote;
import com.emotesmod.EmotesMod;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.render.RenderTickCounter;
import net.minecraft.util.Identifier;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElementRegistry;
import net.minecraft.util.math.MathHelper;

/**
 * Small "now emoting: X" readout with a progress bar, shown above the hotbar while an
 * emote is playing.
 */
public final class EmoteHud {
	private static final int BAR_WIDTH = 60;
	private static final int BAR_HEIGHT = 2;

	private EmoteHud() {
	}

	public static void register() {
		HudElementRegistry.addLast(Identifier.of(EmotesMod.MOD_ID, "active_emote"),
				(DrawContext context, RenderTickCounter tickCounter) -> render(context, tickCounter));
	}

	private static void render(DrawContext context, RenderTickCounter tickCounter) {
		MinecraftClient client = MinecraftClient.getInstance();

		if (client.player == null || client.options.hudHidden) {
			return;
		}

		ClientEmoteState.Active active = ClientEmoteState.get(client.player.getId());

		if (active == null) {
			return;
		}

		float age = ClientEmoteState.ageSeconds(active, tickCounter.getTickProgress(false));
		Emote emote = active.emote();
		float progress = MathHelper.clamp(age / emote.durationSeconds(), 0.0F, 1.0F);

		var textRenderer = client.textRenderer;
		var label = emote.displayNameColored();
		int textWidth = textRenderer.getWidth(label);

		int centerX = context.getScaledWindowWidth() / 2;
		// Sit just above the hotbar so it does not fight the hearts / armour bar.
		int y = context.getScaledWindowHeight() - 68;

		int textX = centerX - textWidth / 2;
		context.drawTextWithShadow(textRenderer, label, textX, y, 0xFFFFFF);

		int barX = centerX - BAR_WIDTH / 2;
		int barY = y + textRenderer.fontHeight + 2;
		context.fill(barX, barY, barX + BAR_WIDTH, barY + BAR_HEIGHT, 0x80000000);
		context.fill(barX, barY, barX + Math.round(BAR_WIDTH * progress), barY + BAR_HEIGHT, 0xFFFFFFFF);
	}
}
