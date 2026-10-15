package dev.keyhud.client;

import dev.keyhud.client.screen.MoveOverlayScreen;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElementRegistry;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.resources.Identifier;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.ItemStack;

import java.util.ArrayDeque;

/**
 * The five movable HUD overlays: FPS, keystrokes (W / A S D / LMB RMB / space, lit
 * green while held), armour durability, ping and a CPS counter. The keystroke boxes
 * read the player's real movement and attack bindings, so rebinding in controls also
 * rebinds the display. Everything can be dragged anywhere from the KeyHUD menu.
 */
public final class KeyHudHud {
	/** Which of the overlays a screen method refers to. */
	public enum Overlay {
		FPS,
		KEYS,
		ARMOR,
		PING,
		CPS
	}

	static final int KEY_SIZE = 20;
	static final int GAP = 2;
	static final int MOUSE_BUTTON_WIDTH = 26;
	static final int SPACE_HEIGHT = 6;

	// Armour rows: a real item icon with the remaining durability next to it, the
	// layout used by the usual PvP clients - helmet, chestplate, leggings, boots,
	// held item, offhand. Only worn, damageable items get a row; empty slots are
	// simply skipped.
	static final int ARMOR_ICON_SIZE = 16;
	static final int ARMOR_ROW_HEIGHT = 16;
	static final int ARMOR_SLOTS = 6;
	static final int ARMOR_WIDTH = 44;
	static final int ARMOR_HEIGHT = ARMOR_SLOTS * ARMOR_ROW_HEIGHT;


	private static final int BOX_BACKGROUND = 0xC814161B;
	private static final int BOX_BACKGROUND_DOWN = 0xE0245B2A;
	private static final int BOX_BORDER = 0xFF33363C;
	private static final int BOX_BORDER_DOWN = 0xFF57C96B;
	private static final int KEY_TEXT = 0xFF8C8C92;
	private static final int KEY_TEXT_DOWN = 0xFFFFFFFF;
	private static final int FPS_BACKGROUND = 0x88000000;
	private static final int DIM_TEXT = 0xFF6A6A70;

	private static final int COLOR_GOOD = 0xFF57C96B;
	private static final int COLOR_OK = 0xFFFFD75F;
	private static final int COLOR_BAD = 0xFFFF5F5F;

	// CPS sampling: press edges collected once per rendered frame, pruned to the last second.
	private static final ArrayDeque<Long> LEFT_CLICKS = new ArrayDeque<>();
	private static final ArrayDeque<Long> RIGHT_CLICKS = new ArrayDeque<>();
	private static boolean wasAttackDown;
	private static boolean wasUseDown;

	private KeyHudHud() {
	}

	public static void register() {
		HudElementRegistry.addLast(Identifier.fromNamespaceAndPath(KeyHudClient.MOD_ID, "overlays"), KeyHudHud::render);
	}

	private static void render(GuiGraphicsExtractor graphics, DeltaTracker deltaTracker) {
		Minecraft client = Minecraft.getInstance();

		if (client.player == null) {
			return;
		}

		sampleClicks(client);

		// While the position editor is open it draws its own live ghost instead.
		// (26.1 has no Hud class, so the F1-hidden check vanilla added later is skipped here.)
		if (client.screen instanceof MoveOverlayScreen) {
			return;
		}

		KeyHudConfig config = KeyHudConfig.get();
		int screenW = graphics.guiWidth();
		int screenH = graphics.guiHeight();

		if (config.showFps) {
			renderFps(graphics, client, posX(Overlay.FPS, config, client, screenW), posY(Overlay.FPS, config, client, screenH));
		}

		if (config.showKeys) {
			renderKeys(graphics, client, posX(Overlay.KEYS, config, client, screenW), posY(Overlay.KEYS, config, client, screenH), false);
		}

		if (config.showArmor) {
			renderArmor(graphics, client, posX(Overlay.ARMOR, config, client, screenW), posY(Overlay.ARMOR, config, client, screenH));
		}

		if (config.showPing) {
			renderPing(graphics, client, posX(Overlay.PING, config, client, screenW), posY(Overlay.PING, config, client, screenH));
		}

		if (config.showCps) {
			renderCps(graphics, client, posX(Overlay.CPS, config, client, screenW), posY(Overlay.CPS, config, client, screenH));
		}
	}

	/** Counts press edges of the attack/use bindings once per frame. */
	private static void sampleClicks(Minecraft client) {
		boolean attack = client.options.keyAttack.isDown();
		boolean use = client.options.keyUse.isDown();
		long now = System.currentTimeMillis();

		if (attack && !wasAttackDown) {
			LEFT_CLICKS.addLast(now);
		}

		if (use && !wasUseDown) {
			RIGHT_CLICKS.addLast(now);
		}

		wasAttackDown = attack;
		wasUseDown = use;

		prune(LEFT_CLICKS, now);
		prune(RIGHT_CLICKS, now);
	}

	private static void prune(ArrayDeque<Long> clicks, long now) {
		while (!clicks.isEmpty() && now - clicks.peekFirst() > 1000L) {
			clicks.removeFirst();
		}
	}

	// ------------------------------------------------------------- size & placement math

	public static int widthOf(Overlay overlay, Minecraft client) {
		return switch (overlay) {
			case FPS -> fpsWidth(client);
			case KEYS -> widgetWidth();
			case ARMOR -> ARMOR_WIDTH;
			case PING -> pingWidth(client);
			case CPS -> cpsWidth(client);
		};
	}

	public static int heightOf(Overlay overlay, Minecraft client) {
		return switch (overlay) {
			case FPS -> fpsHeight(client);
			case KEYS -> widgetHeight();
			case ARMOR -> ARMOR_HEIGHT;
			case PING -> client.font.lineHeight + 3;
			case CPS -> cpsHeight(client);
		};
	}

	public static int widgetWidth() {
		return 3 * KEY_SIZE + 2 * GAP;
	}

	public static int widgetHeight() {
		return 3 * KEY_SIZE + 3 * GAP + SPACE_HEIGHT;
	}

	public static int posX(Overlay overlay, KeyHudConfig config, Minecraft client, int screenW) {
		float fraction = switch (overlay) {
			case FPS -> config.fpsX;
			case KEYS -> config.keysX;
			case ARMOR -> config.armorX;
			case PING -> config.pingX;
			case CPS -> config.cpsX;
		};
		return Math.round(fraction * Math.max(0, screenW - widthOf(overlay, client)));
	}

	public static int posY(Overlay overlay, KeyHudConfig config, Minecraft client, int screenH) {
		float fraction = switch (overlay) {
			case FPS -> config.fpsY;
			case KEYS -> config.keysY;
			case ARMOR -> config.armorY;
			case PING -> config.pingY;
			case CPS -> config.cpsY;
		};
		return Math.round(fraction * Math.max(0, screenH - heightOf(overlay, client)));
	}

	/** Stores a new top-left pixel position of an overlay as clamped fractions. */
	public static void moveTo(Overlay overlay, KeyHudConfig config, Minecraft client,
			int x, int y, int screenW, int screenH) {
		int freeX = Math.max(0, screenW - widthOf(overlay, client));
		int freeY = Math.max(0, screenH - heightOf(overlay, client));
		float fractionX = freeX == 0 ? 0.0F : (float) x / freeX;
		float fractionY = freeY == 0 ? 0.0F : (float) y / freeY;

		switch (overlay) {
			case FPS -> {
				config.fpsX = KeyHudConfig.clamp01(fractionX);
				config.fpsY = KeyHudConfig.clamp01(fractionY);
			}
			case KEYS -> {
				config.keysX = KeyHudConfig.clamp01(fractionX);
				config.keysY = KeyHudConfig.clamp01(fractionY);
			}
			case ARMOR -> {
				config.armorX = KeyHudConfig.clamp01(fractionX);
				config.armorY = KeyHudConfig.clamp01(fractionY);
			}
			case PING -> {
				config.pingX = KeyHudConfig.clamp01(fractionX);
				config.pingY = KeyHudConfig.clamp01(fractionY);
			}
			case CPS -> {
				config.cpsX = KeyHudConfig.clamp01(fractionX);
				config.cpsY = KeyHudConfig.clamp01(fractionY);
			}
		}
	}

	// ------------------------------------------------------------------------ drawing

	public static void renderFps(GuiGraphicsExtractor graphics, Minecraft client, int x, int y) {
		String text = client.getFps() + " FPS";
		int textWidth = client.font.width(text);

		graphics.fill(x, y, x + textWidth + 4, y + fpsHeight(client), FPS_BACKGROUND);
		graphics.text(client.font, text, x + 2, y + 1, 0xFFFFFFFF, true);
	}

	public static void renderKeys(GuiGraphicsExtractor graphics, Minecraft client, int x, int y, boolean preview) {
		int secondRowY = y + KEY_SIZE + GAP;
		int thirdRowY = y + 2 * (KEY_SIZE + GAP);

		// W sits centred above the A S D row; held keys light up green.
		keyBox(graphics, client, x + KEY_SIZE + GAP, y, KEY_SIZE, KEY_SIZE, "W",
				preview || client.options.keyUp.isDown());
		keyBox(graphics, client, x, secondRowY, KEY_SIZE, KEY_SIZE, "A",
				preview || client.options.keyLeft.isDown());
		keyBox(graphics, client, x + KEY_SIZE + GAP, secondRowY, KEY_SIZE, KEY_SIZE, "S",
				preview || client.options.keyDown.isDown());
		keyBox(graphics, client, x + 2 * (KEY_SIZE + GAP), secondRowY, KEY_SIZE, KEY_SIZE, "D",
				preview || client.options.keyRight.isDown());

		keyBox(graphics, client, x, thirdRowY, MOUSE_BUTTON_WIDTH, KEY_SIZE, "LMB",
				preview || client.options.keyAttack.isDown());
		keyBox(graphics, client, x + MOUSE_BUTTON_WIDTH + GAP, thirdRowY, MOUSE_BUTTON_WIDTH, KEY_SIZE, "RMB",
				preview || client.options.keyUse.isDown());

		spaceBar(graphics, x, y + 3 * (KEY_SIZE + GAP), widgetWidth(), preview || client.options.keyJump.isDown());
	}

	public static void renderArmor(GuiGraphicsExtractor graphics, Minecraft client, int x, int y) {
		if (client.player == null) {
			return;
		}

		var player = client.player;
		ItemStack[] stacks = {
				player.getItemBySlot(EquipmentSlot.HEAD),
				player.getItemBySlot(EquipmentSlot.CHEST),
				player.getItemBySlot(EquipmentSlot.LEGS),
				player.getItemBySlot(EquipmentSlot.FEET),
				player.getMainHandItem(),
				player.getOffhandItem(),
		};

		int row = 0;

		for (ItemStack stack : stacks) {
			if (stack.isEmpty() || stack.getMaxDamage() <= 0) {
				continue;
			}

			int rowY = y + row * ARMOR_ROW_HEIGHT;
			graphics.fakeItem(stack, x, rowY);

			// Remaining uses, the number shown next to the icon.
			int remaining = stack.getMaxDamage() - stack.getDamageValue();
			graphics.text(client.font, String.valueOf(remaining),
					x + ARMOR_ICON_SIZE + 3, rowY + 4, 0xFFFFFFFF, true);
			row++;
		}
	}

	public static void renderPing(GuiGraphicsExtractor graphics, Minecraft client, int x, int y) {
		// Our own once-a-second measurement first; until the first pong arrives (or when
		// pongs are not coming back at all) fall back to the tab-list latency.
		int measured = PingProbe.current();
		int latency = measured >= 0 ? measured : tabLatency(client);

		String text = latency >= 0 ? "Ping: " + latency + " ms" : "Ping: --";
		int color = latency < 0
				? DIM_TEXT
				: latency <= 60 ? COLOR_GOOD : latency <= 130 ? COLOR_OK : COLOR_BAD;

		graphics.fill(x, y, x + pingWidth(client), y + client.font.lineHeight + 3, FPS_BACKGROUND);
		graphics.text(client.font, text, x + 2, y + 1, color, true);
	}

	public static void renderCps(GuiGraphicsExtractor graphics, Minecraft client, int x, int y) {
		int lineHeight = client.font.lineHeight + 2;

		graphics.fill(x, y, x + cpsWidth(client), y + cpsHeight(client), FPS_BACKGROUND);
		graphics.text(client.font, "LMB: " + LEFT_CLICKS.size() + " CPS", x + 2, y + 1, 0xFFFFFFFF, true);
		graphics.text(client.font, "RMB: " + RIGHT_CLICKS.size() + " CPS", x + 2, y + lineHeight + 1, 0xFFFFFFFF, true);
	}

	public static void drawOutline(GuiGraphicsExtractor graphics, int x, int y, int width, int height, int color) {
		graphics.fill(x, y, x + width, y + 1, color);
		graphics.fill(x, y + height - 1, x + width, y + height, color);
		graphics.fill(x, y, x + 1, y + height, color);
		graphics.fill(x + width - 1, y, x + width, y + height, color);
	}

	/** Latency the server reports for us through the tab list; -1 when unknown. */
	private static int tabLatency(Minecraft client) {
		var handler = client.getConnection();
		var entry = handler == null || client.player == null ? null : handler.getPlayerInfo(client.player.getUUID());

		return entry == null ? -1 : entry.getLatency();
	}

	private static int fpsWidth(Minecraft client) {
		return client.font.width(client.getFps() + " FPS") + 4;
	}

	private static int fpsHeight(Minecraft client) {
		return client.font.lineHeight + 3;
	}

	private static int pingWidth(Minecraft client) {
		return client.font.width("Ping: 9999 ms") + 4;
	}

	private static int cpsWidth(Minecraft client) {
		return client.font.width("LMB: 99 CPS") + 4;
	}

	private static int cpsHeight(Minecraft client) {
		return 2 * (client.font.lineHeight + 2) + 2;
	}




	private static void keyBox(GuiGraphicsExtractor graphics, Minecraft client, int x, int y,
			int width, int height, String label, boolean down) {
		graphics.fill(x, y, x + width, y + height, down ? BOX_BACKGROUND_DOWN : BOX_BACKGROUND);
		drawOutline(graphics, x, y, width, height, down ? BOX_BORDER_DOWN : BOX_BORDER);

		Font font = client.font;
		int textX = x + (width - font.width(label)) / 2;
		int textY = y + (height - font.lineHeight) / 2;
		graphics.text(font, label, textX, textY, down ? KEY_TEXT_DOWN : KEY_TEXT, true);
	}

	private static void spaceBar(GuiGraphicsExtractor graphics, int x, int y, int width, boolean down) {
		graphics.fill(x, y, x + width, y + SPACE_HEIGHT, down ? BOX_BACKGROUND_DOWN : BOX_BACKGROUND);
		drawOutline(graphics, x, y, width, SPACE_HEIGHT, down ? BOX_BORDER_DOWN : BOX_BORDER);

		// The little dash in the middle, like the usual keystrokes mods draw.
		int dashX = x + width / 2 - 5;
		int dashY = y + SPACE_HEIGHT / 2;
		graphics.fill(dashX, dashY, dashX + 10, dashY + 1, down ? KEY_TEXT_DOWN : KEY_TEXT);
	}
}
