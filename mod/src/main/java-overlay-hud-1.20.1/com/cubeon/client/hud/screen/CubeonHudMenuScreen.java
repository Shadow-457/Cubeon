package com.cubeon.client.hud.screen;

import com.cubeon.client.hud.CubeonHud;
import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.CubeonHud.Overlay;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.text.Text;

import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
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
	/** Toggle rows above the Reset/Done buttons: the five overlays. */
	private static final int ROWS = 6;
	/** The sizes the Size button steps through. */
	private static final float[] SCALES = {0.5F, 0.75F, 1.0F, 1.25F, 1.5F, 2.0F};

	public CubeonHudMenuScreen() {
		super(Text.translatable("cubeonclient.menu.title"));
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

		addDrawableChild(ButtonWidget.builder(enemyHealthLabel(), button -> {
			config.showEnemyHealth = !config.showEnemyHealth;
			CubeonHudConfig.save();
			button.setMessage(enemyHealthLabel());
		}).dimensions(x, y, TOTAL_WIDTH, 20).build());
		y += ROW_HEIGHT;

		int halfWidth = TOTAL_WIDTH / 2 - ROW_GAP / 2;

		addDrawableChild(ButtonWidget.builder(Text.translatable("cubeonclient.menu.reset_positions"), button -> {
			CubeonHudConfig.resetPositions();
			CubeonHudConfig.save();
		}).dimensions(x, y + ROW_GAP, halfWidth, 20).build());

		addDrawableChild(ButtonWidget.builder(Text.translatable("gui.done"), button -> close())
				.dimensions(x + halfWidth + ROW_GAP, y + ROW_GAP, TOTAL_WIDTH - halfWidth - ROW_GAP, 20)
				.build());
	}

	private void addToggleRow(int x, int y, Overlay overlay, BooleanSupplier enabled, Consumer<Boolean> setter,
			Supplier<Text> label) {
		addDrawableChild(ButtonWidget.builder(label.get(), button -> {
			setter.accept(!enabled.getAsBoolean());
			CubeonHudConfig.save();
			button.setMessage(label.get());
		}).dimensions(x, y, TOGGLE_WIDTH, 20).build());

		addDrawableChild(ButtonWidget.builder(Text.translatable("cubeonclient.menu.move"), button -> {
			if (this.client != null) {
				this.client.setScreen(new MoveOverlayScreen(this, overlay));
			}
		}).dimensions(x + TOGGLE_WIDTH + ROW_GAP, y, MOVE_WIDTH, 20).build());

		addDrawableChild(ButtonWidget.builder(sizeLabel(overlay), button -> {
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
		}).dimensions(x + TOGGLE_WIDTH + MOVE_WIDTH + 2 * ROW_GAP, y, SIZE_WIDTH, 20).build());
	}

	/** "Size: 100%" for one overlay. */
	private static Text sizeLabel(Overlay overlay) {
		return Text.translatable("cubeonclient.menu.size",
				Math.round(CubeonHud.scaleOf(overlay) * 100) + "%");
	}

	/** Every row between the title and the bottom of the screen. */
	private static int contentHeight() {
		return ROWS * ROW_HEIGHT + ROW_HEIGHT + ROW_GAP;
	}

	@Override
	public void render(DrawContext context, int mouseX, int mouseY, float delta) {
		/* Screen#render already renders the background before this method is
		 * called, so there is nothing to draw behind the widgets here. */
		super.render(context, mouseX, mouseY, delta);
		context.drawCenteredTextWithShadow(this.textRenderer, this.title, this.width / 2, this.height / 2 - contentHeight() / 2 - 14, 0xFFFFFFFF);
	}

	@Override
	public void removed() {
		CubeonHudConfig.save();
	}

	@Override
	public void close() {
		CubeonHudConfig.save();

		if (this.client != null) {
			this.client.setScreen(null);
		}
	}

	@Override
	public boolean shouldPause() {
		return false;
	}

	private static Text showFpsLabel() {
		return Text.translatable("cubeonclient.menu.show_fps", stateLabel(CubeonHudConfig.get().showFps));
	}

	private static Text showKeysLabel() {
		return Text.translatable("cubeonclient.menu.show_keys", stateLabel(CubeonHudConfig.get().showKeys));
	}

	private static Text showArmorLabel() {
		return Text.translatable("cubeonclient.menu.show_armor", stateLabel(CubeonHudConfig.get().showArmor));
	}

	private static Text showPingLabel() {
		return Text.translatable("cubeonclient.menu.show_ping", stateLabel(CubeonHudConfig.get().showPing));
	}

	private static Text showCpsLabel() {
		return Text.translatable("cubeonclient.menu.show_cps", stateLabel(CubeonHudConfig.get().showCps));
	}

	private static Text enemyHealthLabel() {
		return Text.translatable("cubeonclient.menu.enemy_health", stateLabel(CubeonHudConfig.get().showEnemyHealth));
	}

	private static Text stateLabel(boolean enabled) {
		return Text.translatable(enabled ? "cubeonclient.state.on" : "cubeonclient.state.off");
	}
}
