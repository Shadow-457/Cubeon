package com.cubeon.client.hud.screen;

import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.CubeonHud.Overlay;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;

import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import java.util.function.Supplier;

/**
 * The screen opened by the Cubeon Client menu key. Every overlay gets one row with an on/off
 * toggle next to a "Move" button that opens the drag editor for that overlay, plus a
 * reset button and Done at the bottom.
 */
public final class CubeonHudMenuScreen extends Screen {
	private static final int TOGGLE_WIDTH = 148;
	private static final int MOVE_WIDTH = 64;
	private static final int ROW_GAP = 4;
	private static final int ROW_HEIGHT = 24;
	private static final int TOTAL_WIDTH = TOGGLE_WIDTH + ROW_GAP + MOVE_WIDTH;

	public CubeonHudMenuScreen() {
		super(Component.translatable("cubeonclient.menu.title"));
	}

	@Override
	protected void init() {
		CubeonHudConfig config = CubeonHudConfig.get();
		int x = this.width / 2 - TOTAL_WIDTH / 2;
		int y = this.height / 2 - 66;

		addToggleRow(x, y, Overlay.FPS, () -> config.showFps, v -> config.showFps = v, CubeonHudMenuScreen::showFpsLabel);
		y += ROW_HEIGHT;
		addToggleRow(x, y, Overlay.KEYS, () -> config.showKeys, v -> config.showKeys = v, CubeonHudMenuScreen::showKeysLabel);
		y += ROW_HEIGHT;
		addToggleRow(x, y, Overlay.ARMOR, () -> config.showArmor, v -> config.showArmor = v, CubeonHudMenuScreen::showArmorLabel);
		y += ROW_HEIGHT;
		addToggleRow(x, y, Overlay.PING, () -> config.showPing, v -> config.showPing = v, CubeonHudMenuScreen::showPingLabel);
		y += ROW_HEIGHT;
		addToggleRow(x, y, Overlay.CPS, () -> config.showCps, v -> config.showCps = v, CubeonHudMenuScreen::showCpsLabel);
		y += ROW_HEIGHT;

		float[] scales = {0.5F, 0.75F, 1.0F, 1.25F, 1.5F, 2.0F};

		addRenderableWidget(Button.builder(Component.literal("Scale: " + CubeonHudConfig.get().scale), button -> {
			CubeonHudConfig cfg = CubeonHudConfig.get();
			int idx = 0;

			for (int i = 0; i < scales.length; i++) {
				if (Math.abs(scales[i] - cfg.scale) < 0.001F) {
					idx = i;
					break;
				}
			}

			cfg.scale = scales[(idx + 1) % scales.length];
			CubeonHudConfig.save();
			button.setMessage(Component.literal("Scale: " + cfg.scale));
		}).bounds(x, y + ROW_GAP, TOTAL_WIDTH, 20).build());

		y += ROW_HEIGHT + ROW_GAP;

		int halfWidth = TOTAL_WIDTH / 2 - ROW_GAP / 2;

		addRenderableWidget(Button.builder(Component.translatable("cubeonclient.menu.reset_positions"), button -> {
			CubeonHudConfig.resetPositions();
			CubeonHudConfig.save();
		}).bounds(x, y + ROW_GAP, halfWidth, 20).build());

		addRenderableWidget(Button.builder(Component.translatable("gui.done"), button -> onClose())
				.bounds(x + halfWidth + ROW_GAP, y + ROW_GAP, TOTAL_WIDTH - halfWidth - ROW_GAP, 20)
				.build());
	}

	private void addToggleRow(int x, int y, Overlay overlay, BooleanSupplier enabled, Consumer<Boolean> setter,
			Supplier<Component> label) {
		addRenderableWidget(Button.builder(label.get(), button -> {
			setter.accept(!enabled.getAsBoolean());
			CubeonHudConfig.save();
			button.setMessage(label.get());
		}).bounds(x, y, TOGGLE_WIDTH, 20).build());

		addRenderableWidget(Button.builder(Component.translatable("cubeonclient.menu.move"), button -> {
			if (this.minecraft != null) {
				this.minecraft.setScreen(new MoveOverlayScreen(this, overlay));
			}
		}).bounds(x + TOGGLE_WIDTH + ROW_GAP, y, MOVE_WIDTH, 20).build());
	}

	@Override
	public void extractRenderState(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
		/* The vanilla background is extracted by extractRenderStateWithTooltipAndSubtitles
		 * before this method runs, so there is nothing to draw behind the widgets here. */
		super.extractRenderState(graphics, mouseX, mouseY, partialTick);
		graphics.centeredText(this.font, this.title, this.width / 2, this.height / 2 - 80, 0xFFFFFFFF);
	}

	@Override
	public void removed() {
		CubeonHudConfig.save();
	}

	@Override
	public void onClose() {
		CubeonHudConfig.save();

		if (this.minecraft != null) {
			this.minecraft.setScreen(null);
		}
	}

	@Override
	public boolean isPauseScreen() {
		return false;
	}

	private static Component showFpsLabel() {
		return Component.translatable("cubeonclient.menu.show_fps", stateLabel(CubeonHudConfig.get().showFps));
	}

	private static Component showKeysLabel() {
		return Component.translatable("cubeonclient.menu.show_keys", stateLabel(CubeonHudConfig.get().showKeys));
	}

	private static Component showArmorLabel() {
		return Component.translatable("cubeonclient.menu.show_armor", stateLabel(CubeonHudConfig.get().showArmor));
	}

	private static Component showPingLabel() {
		return Component.translatable("cubeonclient.menu.show_ping", stateLabel(CubeonHudConfig.get().showPing));
	}

	private static Component showCpsLabel() {
		return Component.translatable("cubeonclient.menu.show_cps", stateLabel(CubeonHudConfig.get().showCps));
	}

	private static Component stateLabel(boolean enabled) {
		return Component.translatable(enabled ? "cubeonclient.state.on" : "cubeonclient.state.off");
	}
}
