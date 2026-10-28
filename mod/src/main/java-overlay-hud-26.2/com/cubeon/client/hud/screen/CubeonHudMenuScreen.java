package com.cubeon.client.hud.screen;

import com.cubeon.client.hud.CubeonHud;
import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.CubeonHud.Overlay;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;

import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import java.util.function.IntConsumer;
import java.util.function.IntSupplier;
import java.util.function.Supplier;

/**
 * The screen opened by the Cubeon Client menu key. Every overlay gets one row with an on/off
 * toggle, a "Move" button that opens the drag editor for that overlay and a "Size" button that
 * cycles that overlay's own size, plus a reset button and Done at the bottom.
 *
 * <p>Sizes are per overlay since 2026-10-28: the old single Scale button made the FPS counter
 * and the keystrokes widget share a size, so making one readable made the other huge.
 */
public final class CubeonHudMenuScreen extends Screen {
	private static final int TOGGLE_WIDTH = 118;
	private static final int MOVE_WIDTH = 48;
	private static final int SIZE_WIDTH = 50;
	private static final int ROW_GAP = 4;
	private static final int ROW_HEIGHT = 24;
	private static final int TOTAL_WIDTH = TOGGLE_WIDTH + MOVE_WIDTH + SIZE_WIDTH + 2 * ROW_GAP;
	/**
	 * Toggle rows above the Reset/Done buttons: the five overlays
	 * and Motion Blur.
	 */
	private static final int ROWS = 6;
	/** The sizes the Size button steps through. */
	private static final float[] SCALES = {0.5F, 0.75F, 1.0F, 1.25F, 1.5F, 2.0F};

	public CubeonHudMenuScreen() {
		super(Component.translatable("cubeonclient.menu.title"));
	}

	@Override
	protected void init() {
		CubeonHudConfig config = CubeonHudConfig.get();
		int x = this.width / 2 - TOTAL_WIDTH / 2;
		int y = this.height / 2 - contentHeight() / 2;

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
		// Motion Blur cycles Off -> Low -> Medium -> High (2026-10-24). One row,
		// four states: the old on/off switch forced everyone onto one strength,
		// and the strength is what makes the effect feel smooth rather than
		// smeary. The post effect's BlurAmount is chosen by the same level.
		int[] blurLevels = {0, 1, 2, 3};
		addCycleRow(x, y, blurLevels, () -> config.blurStrength(), config::setBlurStrength,
				CubeonHudMenuScreen::motionBlurLabel);
		y += ROW_HEIGHT;

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
				this.minecraft.gui.setScreen(new MoveOverlayScreen(this, overlay));
			}
		}).bounds(x + TOGGLE_WIDTH + ROW_GAP, y, MOVE_WIDTH, 20).build());

		addRenderableWidget(Button.builder(sizeLabel(overlay), button -> {
			float current = CubeonHud.scaleOf(overlay);
			int index = 0;

			for (int i = 0; i < SCALES.length; i++) {
				if (Math.abs(SCALES[i] - current) < 0.001F) {
					index = i;
					break;
				}
			}

			CubeonHudConfig.get().setScaleFor(CubeonHud.slotOf(overlay),
					SCALES[(index + 1) % SCALES.length]);
			button.setMessage(sizeLabel(overlay));
		}).bounds(x + TOGGLE_WIDTH + MOVE_WIDTH + 2 * ROW_GAP, y, SIZE_WIDTH, 20).build());
	}

	/** "Size: 100%" for one overlay. */
	private static Component sizeLabel(Overlay overlay) {
		return Component.translatable("cubeonclient.menu.size",
				Math.round(CubeonHud.scaleOf(overlay) * 100) + "%");
	}

	/** A row that steps through a fixed list of values on each click. */
	private void addCycleRow(int x, int y, int[] values, IntSupplier getter, IntConsumer setter,
			Supplier<Component> label) {
		addRenderableWidget(Button.builder(label.get(), button -> {
			int current = getter.getAsInt();
			int index = 0;

			for (int i = 0; i < values.length; i++) {
				if (values[i] == current) {
					index = i;
					break;
				}
			}

			setter.accept(values[(index + 1) % values.length]);
			CubeonHudConfig.save();
			button.setMessage(label.get());
		}).bounds(x, y, TOTAL_WIDTH, 20).build());
	}

	/** Every row between the title and the bottom of the screen. */
	private static int contentHeight() {
		return ROWS * ROW_HEIGHT + ROW_HEIGHT + ROW_GAP;
	}

	@Override
	public void extractRenderState(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
		/* The vanilla background is extracted by extractRenderStateWithTooltipAndSubtitles
		 * before this method runs, so there is nothing to draw behind the widgets here. */
		super.extractRenderState(graphics, mouseX, mouseY, partialTick);
		graphics.centeredText(this.font, this.title, this.width / 2, this.height / 2 - contentHeight() / 2 - 14, 0xFFFFFFFF);
	}

	@Override
	public void removed() {
		CubeonHudConfig.save();
	}

	@Override
	public void onClose() {
		CubeonHudConfig.save();

		if (this.minecraft != null) {
			this.minecraft.gui.setScreen(null);
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

	private static Component motionBlurLabel() {
		return Component.translatable("cubeonclient.menu.motion_blur",
				blurLevelLabel(CubeonHudConfig.get().blurStrength()));
	}

	private static Component blurLevelLabel(int level) {
		switch (level) {
			case 1:
				return Component.translatable("cubeonclient.state.low");
			case 2:
				return Component.translatable("cubeonclient.state.medium");
			case 3:
				return Component.translatable("cubeonclient.state.high");
			default:
				return Component.translatable("cubeonclient.state.off");
		}
	}

	private static Component stateLabel(boolean enabled) {
		return Component.translatable(enabled ? "cubeonclient.state.on" : "cubeonclient.state.off");
	}
}
