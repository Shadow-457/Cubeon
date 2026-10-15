package dev.keyhud.client.screen;

import dev.keyhud.client.KeyHudConfig;
import dev.keyhud.client.KeyHudHud;
import dev.keyhud.client.KeyHudHud.Overlay;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.text.Text;

/**
 * Drag editor for one overlay: the live widget is shown where it will sit on the HUD
 * (highlighted so it is easy to see) and can be dragged anywhere with the left mouse
 * button. Done returns to the menu with the new spot saved.
 */
public final class MoveOverlayScreen extends Screen {
	private static final int PADDING = 2;

	private final Screen parent;
	private final Overlay overlay;

	/** Grab offset in pixels from the widget's top-left corner to the click point. */
	private double grabX;
	private double grabY;
	private boolean dragging;

	public MoveOverlayScreen(Screen parent, Overlay overlay) {
		super(Text.translatable(switch (overlay) {
				case FPS -> "keyhud.editor.fps";
				case KEYS -> "keyhud.editor.keys";
				case ARMOR -> "keyhud.editor.armor";
				case PING -> "keyhud.editor.ping";
				case CPS -> "keyhud.editor.cps";
			}));
		this.parent = parent;
		this.overlay = overlay;
	}

	@Override
	protected void init() {
		addDrawableChild(ButtonWidget.builder(Text.translatable("gui.done"), button -> close())
				.dimensions(this.width / 2 - 100, this.height - 28, 200, 20)
				.build());
	}

	@Override
	public void renderBackground(DrawContext context, int mouseX, int mouseY, float delta) {
		// Translucent darkening instead of the vanilla background, so the world and the
		// real HUD stay visible while choosing a spot.
		context.fill(0, 0, this.width, this.height, 0x90000000);
	}

	@Override
	public void render(DrawContext context, int mouseX, int mouseY, float delta) {
		super.render(context, mouseX, mouseY, delta);

		if (this.client == null) {
			return;
		}

		KeyHudConfig config = KeyHudConfig.get();
		int x = KeyHudHud.posX(overlay, config, this.client, this.width);
		int y = KeyHudHud.posY(overlay, config, this.client, this.height);
		int w = KeyHudHud.widthOf(overlay, this.client);
		int h = KeyHudHud.heightOf(overlay, this.client);

		// Live ghost of the overlay itself; the keystrokes widget is drawn fully lit
		// so it reads as a preview.
		switch (overlay) {
			case FPS -> KeyHudHud.renderFps(context, this.client, x, y);
			case KEYS -> KeyHudHud.renderKeys(context, this.client, x, y, true);
			case ARMOR -> KeyHudHud.renderArmor(context, this.client, x, y);
			case PING -> KeyHudHud.renderPing(context, this.client, x, y);
			case CPS -> KeyHudHud.renderCps(context, this.client, x, y);
		}

		KeyHudHud.drawOutline(context, x - PADDING, y - PADDING, w + 2 * PADDING, h + 2 * PADDING, 0xFFFFFFFF);
		context.drawCenteredTextWithShadow(this.textRenderer, Text.translatable("keyhud.editor.hint"),
				this.width / 2, 12, 0xFFFFC87D);
		context.drawCenteredTextWithShadow(this.textRenderer, this.title, this.width / 2, this.height - 46, 0xFFFFFFFF);
	}

	@Override
	public boolean mouseClicked(double mouseX, double mouseY, int button) {
		// Let the Done button (and focus handling) process the click first.
		if (super.mouseClicked(mouseX, mouseY, button)) {
			return true;
		}

		if (button == 0 && this.client != null && isOverWidget(mouseX, mouseY)) {
			KeyHudConfig config = KeyHudConfig.get();
			this.grabX = mouseX - KeyHudHud.posX(overlay, config, this.client, this.width);
			this.grabY = mouseY - KeyHudHud.posY(overlay, config, this.client, this.height);
			this.dragging = true;
			return true;
		}

		return false;
	}

	@Override
	public boolean mouseDragged(double mouseX, double mouseY, int button, double offsetX, double offsetY) {
		if (super.mouseDragged(mouseX, mouseY, button, offsetX, offsetY)) {
			return true;
		}

		if (this.dragging && this.client != null) {
			KeyHudHud.moveTo(overlay, KeyHudConfig.get(), this.client,
					(int) Math.round(mouseX - this.grabX), (int) Math.round(mouseY - this.grabY),
					this.width, this.height);
			return true;
		}

		return false;
	}

	@Override
	public boolean mouseReleased(double mouseX, double mouseY, int button) {
		if (this.dragging) {
			this.dragging = false;
			KeyHudConfig.save();
			return true;
		}

		return super.mouseReleased(mouseX, mouseY, button);
	}

	@Override
	public void removed() {
		KeyHudConfig.save();
	}

	@Override
	public void close() {
		KeyHudConfig.save();

		if (this.client != null) {
			this.client.setScreen(this.parent);
		}
	}

	@Override
	public boolean shouldPause() {
		return false;
	}

	private boolean isOverWidget(double mouseX, double mouseY) {
		KeyHudConfig config = KeyHudConfig.get();
		int x = KeyHudHud.posX(overlay, config, this.client, this.width) - PADDING;
		int y = KeyHudHud.posY(overlay, config, this.client, this.height) - PADDING;
		int w = KeyHudHud.widthOf(overlay, this.client) + 2 * PADDING;
		int h = KeyHudHud.heightOf(overlay, this.client) + 2 * PADDING;

		return mouseX >= x && mouseX <= x + w && mouseY >= y && mouseY <= y + h;
	}
}
