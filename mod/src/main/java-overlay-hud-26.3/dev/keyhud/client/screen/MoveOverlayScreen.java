package dev.keyhud.client.screen;

import dev.keyhud.client.KeyHudConfig;
import dev.keyhud.client.KeyHudHud;
import dev.keyhud.client.KeyHudHud.Overlay;
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

		KeyHudConfig config = KeyHudConfig.get();
		int x = KeyHudHud.posX(overlay, config, this.minecraft, this.width);
		int y = KeyHudHud.posY(overlay, config, this.minecraft, this.height);
		int w = KeyHudHud.widthOf(overlay, this.minecraft);
		int h = KeyHudHud.heightOf(overlay, this.minecraft);

		// Live ghost of the overlay itself; the keystrokes widget is drawn fully lit
		// so it reads as a preview.
		switch (overlay) {
			case FPS -> KeyHudHud.renderFps(graphics, this.minecraft, x, y);
			case KEYS -> KeyHudHud.renderKeys(graphics, this.minecraft, x, y, true);
			case ARMOR -> KeyHudHud.renderArmor(graphics, this.minecraft, x, y);
			case PING -> KeyHudHud.renderPing(graphics, this.minecraft, x, y);
			case CPS -> KeyHudHud.renderCps(graphics, this.minecraft, x, y);
		}

		KeyHudHud.drawOutline(graphics, x - PADDING, y - PADDING, w + 2 * PADDING, h + 2 * PADDING, 0xFFFFFFFF);
		graphics.centeredText(this.font, Component.translatable("keyhud.editor.hint"), this.width / 2, 12, 0xFFFFC87D);
		graphics.centeredText(this.font, this.title, this.width / 2, this.height - 46, 0xFFFFFFFF);
	}

	@Override
	public boolean mouseClicked(MouseButtonEvent event, boolean doubleClick) {
		// Let the Done button (and focus handling) process the click first.
		if (super.mouseClicked(event, doubleClick)) {
			return true;
		}

		// 26.3 moved input from GLFW to SDL, and SDL numbers the mouse buttons
		// from 1 (SDL_BUTTON_LEFT = 1, middle = 2, right = 3) where GLFW started
		// at 0. Vanilla's own ContainerEventHandler now drags on button() == 1;
		// the old "== 0" never matched here, so nothing could ever be grabbed -
		// "can't move the widgets" on 26.3 only. 26.1/26.2 are still GLFW (== 0).
		if (event.button() == 1 && this.minecraft != null && isOverWidget(event.x(), event.y())) {
			KeyHudConfig config = KeyHudConfig.get();
			this.grabX = event.x() - KeyHudHud.posX(overlay, config, this.minecraft, this.width);
			this.grabY = event.y() - KeyHudHud.posY(overlay, config, this.minecraft, this.height);
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
			KeyHudHud.moveTo(overlay, KeyHudConfig.get(), this.minecraft,
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
			KeyHudConfig.save();
			return true;
		}

		return super.mouseReleased(event);
	}

	@Override
	public void removed() {
		KeyHudConfig.save();
	}

	@Override
	public void onClose() {
		KeyHudConfig.save();

		if (this.minecraft != null) {
			this.minecraft.gui.setScreen(this.parent);
		}
	}

	@Override
	public boolean isPauseScreen() {
		return false;
	}

	private boolean isOverWidget(double mouseX, double mouseY) {
		KeyHudConfig config = KeyHudConfig.get();
		int x = KeyHudHud.posX(overlay, config, this.minecraft, this.width) - PADDING;
		int y = KeyHudHud.posY(overlay, config, this.minecraft, this.height) - PADDING;
		int w = KeyHudHud.widthOf(overlay, this.minecraft) + 2 * PADDING;
		int h = KeyHudHud.heightOf(overlay, this.minecraft) + 2 * PADDING;

		return mouseX >= x && mouseX <= x + w && mouseY >= y && mouseY <= y + h;
	}
}
