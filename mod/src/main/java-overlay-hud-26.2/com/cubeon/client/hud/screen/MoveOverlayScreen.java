package com.cubeon.client.hud.screen;

import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.CubeonHud;
import com.cubeon.client.hud.CubeonHud.Overlay;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.input.MouseButtonEvent;
import net.minecraft.network.chat.Component;

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
		super(Component.translatable(switch (overlay) {
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
		addRenderableWidget(Button.builder(Component.translatable("gui.done"), button -> onClose())
				.bounds(this.width / 2 - 100, this.height - 28, 200, 20)
				.build());
	}

	@Override
	public void extractBackground(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
		// Translucent darkening instead of the vanilla background, so the world and the
		// real HUD stay visible while choosing a spot.
		graphics.fill(0, 0, this.width, this.height, 0x90000000);
	}

	@Override
	public void extractRenderState(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
		super.extractRenderState(graphics, mouseX, mouseY, partialTick);

		if (this.minecraft == null) {
			return;
		}

		CubeonHudConfig config = CubeonHudConfig.get();
		int x = CubeonHud.posX(overlay, config, this.minecraft, this.width);
		int y = CubeonHud.posY(overlay, config, this.minecraft, this.height);
		int w = CubeonHud.widthOf(overlay, this.minecraft);
		int h = CubeonHud.heightOf(overlay, this.minecraft);

		// Live ghost of the overlay itself; the keystrokes widget is drawn fully lit
		// so it reads as a preview.
		switch (overlay) {
			case FPS -> CubeonHud.renderFps(graphics, this.minecraft, x, y);
			case KEYS -> CubeonHud.renderKeys(graphics, this.minecraft, x, y, true);
			case ARMOR -> CubeonHud.renderArmor(graphics, this.minecraft, x, y);
			case PING -> CubeonHud.renderPing(graphics, this.minecraft, x, y);
			case CPS -> CubeonHud.renderCps(graphics, this.minecraft, x, y);
		}

		CubeonHud.drawOutline(graphics, x - PADDING, y - PADDING, w + 2 * PADDING, h + 2 * PADDING, 0xFFFFFFFF);
		graphics.centeredText(this.font, Component.translatable("cubeonclient.editor.hint"), this.width / 2, 12, 0xFFFFC87D);
		graphics.centeredText(this.font, this.title, this.width / 2, this.height - 46, 0xFFFFFFFF);
	}

	@Override
	public boolean mouseClicked(MouseButtonEvent event, boolean doubleClick) {
		// Let the Done button (and focus handling) process the click first.
		if (super.mouseClicked(event, doubleClick)) {
			return true;
		}

		if (event.button() == 0 && this.minecraft != null && isOverWidget(event.x(), event.y())) {
			CubeonHudConfig config = CubeonHudConfig.get();
			this.grabX = event.x() - CubeonHud.posX(overlay, config, this.minecraft, this.width);
			this.grabY = event.y() - CubeonHud.posY(overlay, config, this.minecraft, this.height);
			this.dragging = true;
			return true;
		}

		return false;
	}

	@Override
	public boolean mouseDragged(MouseButtonEvent event, double dragX, double dragY) {
		if (super.mouseDragged(event, dragX, dragY)) {
			return true;
		}

		if (this.dragging && this.minecraft != null) {
			CubeonHud.moveTo(overlay, CubeonHudConfig.get(), this.minecraft,
					(int) Math.round(event.x() - this.grabX), (int) Math.round(event.y() - this.grabY),
					this.width, this.height);
			return true;
		}

		return false;
	}

	@Override
	public boolean mouseReleased(MouseButtonEvent event) {
		if (this.dragging) {
			this.dragging = false;
			CubeonHudConfig.save();
			return true;
		}

		return super.mouseReleased(event);
	}

	@Override
	public void removed() {
		CubeonHudConfig.save();
	}

	@Override
	public void onClose() {
		CubeonHudConfig.save();

		if (this.minecraft != null) {
			this.minecraft.gui.setScreen(this.parent);
		}
	}

	@Override
	public boolean isPauseScreen() {
		return false;
	}

	private boolean isOverWidget(double mouseX, double mouseY) {
		CubeonHudConfig config = CubeonHudConfig.get();
		int x = CubeonHud.posX(overlay, config, this.minecraft, this.width) - PADDING;
		int y = CubeonHud.posY(overlay, config, this.minecraft, this.height) - PADDING;
		int w = CubeonHud.widthOf(overlay, this.minecraft) + 2 * PADDING;
		int h = CubeonHud.heightOf(overlay, this.minecraft) + 2 * PADDING;

		return mouseX >= x && mouseX <= x + w && mouseY >= y && mouseY <= y + h;
	}
}
