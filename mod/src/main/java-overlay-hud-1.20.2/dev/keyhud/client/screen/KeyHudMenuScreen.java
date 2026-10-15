package dev.keyhud.client.screen;

import dev.keyhud.client.KeyHudConfig;
import dev.keyhud.client.KeyHudHud.Overlay;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.text.Text;

import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import java.util.function.Supplier;

/**
 * The screen opened by the KeyHUD menu key. Every overlay gets one row with an on/off
 * toggle next to a "Move" button that opens the drag editor for that overlay, plus a
 * reset button and Done at the bottom.
 */
public final class KeyHudMenuScreen extends Screen {
	private static final int TOGGLE_WIDTH = 148;
	private static final int MOVE_WIDTH = 64;
	private static final int ROW_GAP = 4;
	private static final int ROW_HEIGHT = 24;
	private static final int TOTAL_WIDTH = TOGGLE_WIDTH + ROW_GAP + MOVE_WIDTH;

	public KeyHudMenuScreen() {
		super(Text.translatable("keyhud.menu.title"));
	}

	@Override
	protected void init() {
		KeyHudConfig config = KeyHudConfig.get();
		int x = this.width / 2 - TOTAL_WIDTH / 2;
		int y = this.height / 2 - 66;

		addToggleRow(x, y, Overlay.FPS, () -> config.showFps, v -> config.showFps = v, KeyHudMenuScreen::showFpsLabel);
		y += ROW_HEIGHT;
		addToggleRow(x, y, Overlay.KEYS, () -> config.showKeys, v -> config.showKeys = v, KeyHudMenuScreen::showKeysLabel);
		y += ROW_HEIGHT;
		addToggleRow(x, y, Overlay.ARMOR, () -> config.showArmor, v -> config.showArmor = v, KeyHudMenuScreen::showArmorLabel);
		y += ROW_HEIGHT;
		addToggleRow(x, y, Overlay.PING, () -> config.showPing, v -> config.showPing = v, KeyHudMenuScreen::showPingLabel);
		y += ROW_HEIGHT;
		addToggleRow(x, y, Overlay.CPS, () -> config.showCps, v -> config.showCps = v, KeyHudMenuScreen::showCpsLabel);
		y += ROW_HEIGHT;

		int halfWidth = TOTAL_WIDTH / 2 - ROW_GAP / 2;

		addDrawableChild(ButtonWidget.builder(Text.translatable("keyhud.menu.reset_positions"), button -> {
			KeyHudConfig.resetPositions();
			KeyHudConfig.save();
		}).dimensions(x, y + ROW_GAP, halfWidth, 20).build());

		addDrawableChild(ButtonWidget.builder(Text.translatable("gui.done"), button -> close())
				.dimensions(x + halfWidth + ROW_GAP, y + ROW_GAP, TOTAL_WIDTH - halfWidth - ROW_GAP, 20)
				.build());
	}

	private void addToggleRow(int x, int y, Overlay overlay, BooleanSupplier enabled, Consumer<Boolean> setter,
			Supplier<Text> label) {
		addDrawableChild(ButtonWidget.builder(label.get(), button -> {
			setter.accept(!enabled.getAsBoolean());
			KeyHudConfig.save();
			button.setMessage(label.get());
		}).dimensions(x, y, TOGGLE_WIDTH, 20).build());

		addDrawableChild(ButtonWidget.builder(Text.translatable("keyhud.menu.move"), button -> {
			if (this.client != null) {
				this.client.setScreen(new MoveOverlayScreen(this, overlay));
			}
		}).dimensions(x + TOGGLE_WIDTH + ROW_GAP, y, MOVE_WIDTH, 20).build());
	}

	@Override
	public void render(DrawContext context, int mouseX, int mouseY, float delta) {
		/* Screen#render already renders the background before this method is
		 * called, so there is nothing to draw behind the widgets here. */
		super.render(context, mouseX, mouseY, delta);
		context.drawCenteredTextWithShadow(this.textRenderer, this.title, this.width / 2, this.height / 2 - 80, 0xFFFFFFFF);
	}

	@Override
	public void removed() {
		KeyHudConfig.save();
	}

	@Override
	public void close() {
		KeyHudConfig.save();

		if (this.client != null) {
			this.client.setScreen(null);
		}
	}

	@Override
	public boolean shouldPause() {
		return false;
	}

	private static Text showFpsLabel() {
		return Text.translatable("keyhud.menu.show_fps", stateLabel(KeyHudConfig.get().showFps));
	}

	private static Text showKeysLabel() {
		return Text.translatable("keyhud.menu.show_keys", stateLabel(KeyHudConfig.get().showKeys));
	}

	private static Text showArmorLabel() {
		return Text.translatable("keyhud.menu.show_armor", stateLabel(KeyHudConfig.get().showArmor));
	}

	private static Text showPingLabel() {
		return Text.translatable("keyhud.menu.show_ping", stateLabel(KeyHudConfig.get().showPing));
	}

	private static Text showCpsLabel() {
		return Text.translatable("keyhud.menu.show_cps", stateLabel(KeyHudConfig.get().showCps));
	}

	private static Text stateLabel(boolean enabled) {
		return Text.translatable(enabled ? "keyhud.state.on" : "keyhud.state.off");
	}
}
