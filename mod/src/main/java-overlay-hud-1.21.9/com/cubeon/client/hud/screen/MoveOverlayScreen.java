package com.cubeon.client.hud.screen;

import org.lwjgl.glfw.GLFW;
import net.minecraft.client.input.KeyInput;
import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.ui.ClientUi;
import com.cubeon.client.ui.HudEditorChrome;
import com.cubeon.client.hud.CubeonHud;
import com.cubeon.client.hud.CubeonHud.Overlay;
import net.minecraft.client.gui.Click;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.text.Text;

/**
 * Drag editor: enabled peers stay visible beside the selected live widget
 * (highlighted so it is easy to see) and can be dragged anywhere with the left mouse
 * button. Done returns to the menu with the new spot saved.
 */
public final class MoveOverlayScreen extends Screen {
	private static final int PADDING = 2;
    private static final Overlay[] OVERLAYS = Overlay.values();

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
                default -> "cubeonclient.hud." + CubeonHud.slotOf(overlay);
			}));
		this.parent = parent;
		this.overlay = overlay;
	}

	@Override
	protected void init() { }

	@Override
	public void renderBackground(DrawContext context, int mouseX, int mouseY, float delta) {
		// Translucent darkening instead of the vanilla background, so the world and the
		// real HUD stay visible while choosing a spot.
		context.fill(0, 0, this.width, this.height, 0x22000000);
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

        for (Overlay other : OVERLAYS) {
            if (other == overlay || !CubeonHud.enabled(other, config)) continue;
            CubeonHud.renderPreview(context, this.client, config, other, this.width, this.height);
            HudEditorChrome.peer(canvas(context), this.width, this.height,
                    CubeonHud.posX(other, config, this.client, this.width),
                    CubeonHud.posY(other, config, this.client, this.height),
                    CubeonHud.widthOf(other, this.client), CubeonHud.heightOf(other, this.client), x, y, w, h);
        }
        CubeonHud.renderPreview(context, this.client, config, overlay, this.width, this.height);

        HudEditorChrome.render(canvas(context), this.width, this.height, this.title.getString(),
                mouseX, mouseY, x, y, w, h, this.dragging);
	}

	@Override
	public boolean mouseClicked(Click click, boolean doubleClick) {
        if (click.button() == 0 && HudEditorChrome.done(this.width, this.height, click.x(), click.y())) { close(); return true; }
        if (click.button() == 1) { close(); return true; }

		// Preserve native screen focus handling before grabbing the preview.
		if (super.mouseClicked(click, doubleClick)) {
			return true;
		}

		if (click.button() == 0 && this.client != null && isOverWidget(click.x(), click.y())) {
			CubeonHudConfig config = CubeonHudConfig.get();
			this.grabX = click.x() - CubeonHud.posX(overlay, config, this.client, this.width);
			this.grabY = click.y() - CubeonHud.posY(overlay, config, this.client, this.height);
			this.dragging = true;
			return true;
		}

		return false;
	}

	@Override
	public boolean mouseDragged(Click click, double horizontalAmount, double verticalAmount) {
		if (super.mouseDragged(click, horizontalAmount, verticalAmount)) {
			return true;
		}

		if (this.dragging && this.client != null) {
			CubeonHud.moveTo(overlay, CubeonHudConfig.get(), this.client,
					(int) Math.round(click.x() - this.grabX), (int) Math.round(click.y() - this.grabY),
					this.width, this.height);
			return true;
		}

		return false;
	}

	@Override
	public boolean mouseReleased(Click click) {
		if (this.dragging) {
			this.dragging = false;
			CubeonHudConfig.save();
			return true;
		}

		return super.mouseReleased(click);
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

    @Override public boolean keyPressed(KeyInput event) {
        return key(event.key()) || super.keyPressed(event);
    }
    private boolean key(int key) {
        if (key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER) { close(); return true; }
        return false;
    }
    private ClientUi.Canvas canvas(DrawContext context) { return new ClientUi.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { context.fill(x0, y0, x1, y1, color); }
            public boolean textures() { return true; }
            public void image(String path, int x, int y, int w, int h, int u, int v,
                              int regionW, int regionH, int textureW, int textureH, int color) {
                ClientUiDraw.image(context, path, x, y, w, h, u, v, regionW, regionH, textureW, textureH, color);
            }
            public void text(String value, int x, int y, int color) {
                var label = ClientUiFont.text(value);
                context.drawText(textRenderer, label, x - textRenderer.getWidth(label) / 2, y, color, false);
            }
            public int width(String value) { return textRenderer.getWidth(ClientUiFont.text(value)); }
            public String translate(String key) { return Text.translatable(key).getString(); }
        }; }

	private boolean isOverWidget(double mouseX, double mouseY) {
		CubeonHudConfig config = CubeonHudConfig.get();
		int x = CubeonHud.posX(overlay, config, this.client, this.width) - PADDING;
		int y = CubeonHud.posY(overlay, config, this.client, this.height) - PADDING;
		int w = CubeonHud.widthOf(overlay, this.client) + 2 * PADDING;
		int h = CubeonHud.heightOf(overlay, this.client) + 2 * PADDING;

		return mouseX >= x && mouseX <= x + w && mouseY >= y && mouseY <= y + h;
	}
}
