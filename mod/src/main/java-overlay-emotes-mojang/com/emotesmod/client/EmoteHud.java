package com.emotesmod.client;

import com.emotesmod.Emote;
import com.emotesmod.EmotesMod;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElementRegistry;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.resources.Identifier;
import net.minecraft.util.Mth;

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
		HudElementRegistry.addLast(Identifier.fromNamespaceAndPath(EmotesMod.MOD_ID, "active_emote"),
				EmoteHud::render);
	}

	private static void render(GuiGraphicsExtractor graphics, DeltaTracker deltaTracker) {
		Minecraft client = Minecraft.getInstance();

		if (client.player == null) {
			return;
		}

		if (client.getDebugOverlay().showDebugScreen()) {
			return;
		}

		ClientEmoteState.Active active = ClientEmoteState.getLocal();

		if (active == null) {
			return;
		}

		float age = ClientEmoteState.ageSeconds(active, deltaTracker.getGameTimeDeltaPartialTick(false));
		Emote emote = active.emote();
		float progress = Mth.clamp(age / emote.durationSeconds(), 0.0F, 1.0F);

		Font font = client.font;
		String label = emote.displayNameColored().getString();
		int textWidth = font.width(label);

		int centerX = graphics.guiWidth() / 2;
		// Sit just above the hotbar so it does not fight the hearts / armour bar.
		int y = graphics.guiHeight() - 68;

		int textX = centerX - textWidth / 2;
		graphics.text(font, label, textX, y, 0xFFFFFFFF);

		int barX = centerX - BAR_WIDTH / 2;
		int barY = y + font.lineHeight + 2;
		graphics.fill(barX, barY, barX + BAR_WIDTH, barY + BAR_HEIGHT, 0x80000000);
		graphics.fill(barX, barY, barX + Math.round(BAR_WIDTH * progress), barY + BAR_HEIGHT, 0xFFFFFFFF);
	}
}
