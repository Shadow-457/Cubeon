package com.cubeon.client.hud.screen;

import org.lwjgl.glfw.GLFW;
import net.minecraft.client.input.KeyEvent;
import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.ui.ClientUi;
import com.cubeon.client.ui.HudEditorChrome;
import com.cubeon.client.hud.CubeonHud;
import com.cubeon.client.hud.CubeonHud.Overlay;
import net.minecraft.client.gui.GuiGraphicsExtractor;
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
	protected void init() { }

	@Override
	public void extractBackground(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
		// Translucent darkening instead of the vanilla background, so the world and the
		// real HUD stay visible while choosing a spot.
		graphics.fill(0, 0, this.width, this.height, ClientUi.BACKDROP);
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

		float hudScale = CubeonHud.scaleOf(overlay);
		graphics.pose().pushMatrix();
		graphics.pose().scale(hudScale, hudScale);

		// Live ghost of the overlay itself; the keystrokes widget is drawn fully lit
		// so it reads as a preview.
		switch (overlay) {
			case FPS -> CubeonHud.renderFps(graphics, this.minecraft, (int) (x / hudScale), (int) (y / hudScale));
			case KEYS -> CubeonHud.renderKeys(graphics, this.minecraft, (int) (x / hudScale), (int) (y / hudScale), true);
			case ARMOR -> CubeonHud.renderArmor(graphics, this.minecraft, (int) (x / hudScale), (int) (y / hudScale));
			case PING -> CubeonHud.renderPing(graphics, this.minecraft, (int) (x / hudScale), (int) (y / hudScale));
			case CPS -> CubeonHud.renderCps(graphics, this.minecraft, (int) (x / hudScale), (int) (y / hudScale));
		}

		graphics.pose().popMatrix();

        HudEditorChrome.render(canvas(graphics), this.width, this.height, this.title.getString(),
                mouseX, mouseY, x, y, w, h, this.dragging);
	}

	@Override
	public boolean mouseClicked(MouseButtonEvent event, boolean doubleClick) {
        if (event.button() == 0 && HudEditorChrome.done(this.width, this.height, event.x(), event.y())) { onClose(); return true; }
        if (event.button() == 1) { onClose(); return true; }

		// Preserve native screen focus handling before grabbing the preview.
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
			this.minecraft.setScreen(this.parent);
		}
	}

	@Override
	public boolean isPauseScreen() {
		return false;
	}

    @Override public boolean keyPressed(KeyEvent event) {
        return key(event.key()) || super.keyPressed(event);
    }
    private boolean key(int key) {
        if (key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER) { onClose(); return true; }
        return false;
    }
    private ClientUi.Canvas canvas(GuiGraphicsExtractor graphics) { return new ClientUi.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { graphics.fill(x0, y0, x1, y1, color); }
            public boolean textures() { return true; }
            public void image(String path, int x, int y, int w, int h, int u, int v,
                              int regionW, int regionH, int textureW, int textureH, int color) {
                ClientUiDraw.image(graphics, path, x, y, w, h, u, v, regionW, regionH, textureW, textureH, color);
            }
            public void text(String value, int x, int y, int color) {
                var label = ClientUiFont.text(value);
                graphics.text(font, label, x - font.width(label) / 2, y, color, false);
            }
            public int width(String value) { return font.width(ClientUiFont.text(value)); }
            public String translate(String key) { return Component.translatable(key).getString(); }
        }; }

	private boolean isOverWidget(double mouseX, double mouseY) {
		CubeonHudConfig config = CubeonHudConfig.get();
		int x = CubeonHud.posX(overlay, config, this.minecraft, this.width) - PADDING;
		int y = CubeonHud.posY(overlay, config, this.minecraft, this.height) - PADDING;
		int w = CubeonHud.widthOf(overlay, this.minecraft) + 2 * PADDING;
		int h = CubeonHud.heightOf(overlay, this.minecraft) + 2 * PADDING;

		return mouseX >= x && mouseX <= x + w && mouseY >= y && mouseY <= y + h;
	}
}
