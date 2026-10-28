package com.cubeon.client.hud.screen;

import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.CubeonHud;
import com.cubeon.client.hud.CubeonHud.Overlay;
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
				case FPS -> "cubeonclient.editor.fps";
				case KEYS -> "cubeonclient.editor.keys";
				case ARMOR -> "cubeonclient.editor.armor";
				case PING -> "cubeonclient.editor.ping";
				case CPS -> "cubeonclient.editor.cps";
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

		CubeonHudConfig config = CubeonHudConfig.get();
		int x = CubeonHud.posX(overlay, config, this.client, this.width);
		int y = CubeonHud.posY(overlay, config, this.client, this.height);
		int w = CubeonHud.widthOf(overlay, this.client);
		int h = CubeonHud.heightOf(overlay, this.client);

		// Live ghost of the overlay itself; the keystrokes widget is drawn fully lit
		// so it reads as a preview.
		float hudScale = CubeonHud.scaleOf(overlay);
		context.getMatrices().push();
		context.getMatrices().scale(hudScale, hudScale, 1.0F);

		switch (overlay) {
			case FPS -> CubeonHud.renderFps(context, this.client, (int) (x / hudScale), (int) (y / hudScale));
			case KEYS -> CubeonHud.renderKeys(context, this.client, (int) (x / hudScale), (int) (y / hudScale), true);
			case ARMOR -> CubeonHud.renderArmor(context, this.client, (int) (x / hudScale), (int) (y / hudScale));
			case PING -> CubeonHud.renderPing(context, this.client, (int) (x / hudScale), (int) (y / hudScale));
			case CPS -> CubeonHud.renderCps(context, this.client, (int) (x / hudScale), (int) (y / hudScale));
		}

		context.getMatrices().pop();

		CubeonHud.drawOutline(context, x - PADDING, y - PADDING, w + 2 * PADDING, h + 2 * PADDING, 0xFFFFFFFF);
		context.drawCenteredTextWithShadow(this.textRenderer, Text.translatable("cubeonclient.editor.hint"),
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
			CubeonHudConfig config = CubeonHudConfig.get();
			this.grabX = mouseX - CubeonHud.posX(overlay, config, this.client, this.width);
			this.grabY = mouseY - CubeonHud.posY(overlay, config, this.client, this.height);
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
			CubeonHud.moveTo(overlay, CubeonHudConfig.get(), this.client,
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
			CubeonHudConfig.save();
			return true;
		}

		return super.mouseReleased(mouseX, mouseY, button);
	}

	@Override
	public void removed() {
		CubeonHudConfig.save();
	}

	@Override
	public void close() {
		CubeonHudConfig.save();

		if (this.client != null) {
			this.client.setScreen(this.parent);
		}
	}

	@Override
	public boolean shouldPause() {
		return false;
	}

	private boolean isOverWidget(double mouseX, double mouseY) {
		CubeonHudConfig config = CubeonHudConfig.get();
		int x = CubeonHud.posX(overlay, config, this.client, this.width) - PADDING;
		int y = CubeonHud.posY(overlay, config, this.client, this.height) - PADDING;
		int w = CubeonHud.widthOf(overlay, this.client) + 2 * PADDING;
		int h = CubeonHud.heightOf(overlay, this.client) + 2 * PADDING;

		return mouseX >= x && mouseX <= x + w && mouseY >= y && mouseY <= y + h;
	}
}
