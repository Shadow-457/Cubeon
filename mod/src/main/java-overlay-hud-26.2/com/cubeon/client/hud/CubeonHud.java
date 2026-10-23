package com.cubeon.client.hud;

import com.cubeon.client.hud.screen.MoveOverlayScreen;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElementRegistry;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.resources.Identifier;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

import java.util.ArrayDeque;

/**
 * The five movable HUD overlays: FPS, keystrokes (W / A S D / LMB RMB / space, lit
 * green while held), armour durability, ping and a CPS counter. The keystroke boxes
 * read the player's real movement and attack bindings, so rebinding in controls also
 * rebinds the display. Everything can be dragged anywhere from the Cubeon Client menu.
 */
public final class CubeonHud {
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

	private CubeonHud() {
	}

	public static void register() {
		HudElementRegistry.addLast(Identifier.fromNamespaceAndPath(CubeonHudClient.MOD_ID, "overlays"), CubeonHud::render);
	}

	private static void render(GuiGraphicsExtractor graphics, DeltaTracker deltaTracker) {
		Minecraft client = Minecraft.getInstance();

		if (client.player == null) {
			return;
		}

		sampleClicks(client);

		// While the position editor is open it draws its own live ghost instead.
		if (client.getDebugOverlay().showDebugScreen()) {
			return;
		}

		if (client.getDebugOverlay().showDebugScreen()) {
			return;
		}

		if (client.gui.hud.isHidden() || client.gui.screen() instanceof MoveOverlayScreen) {
			return;
		}

		CubeonHudConfig config = CubeonHudConfig.get();
		int screenW = graphics.guiWidth();
		int screenH = graphics.guiHeight();

		float hudScale = config.scale;
		graphics.pose().pushMatrix();
		graphics.pose().scale(hudScale, hudScale);

		if (config.showFps) {
			renderFps(graphics, client, (int) (posX(Overlay.FPS, config, client, screenW) / hudScale),
					(int) (posY(Overlay.FPS, config, client, screenH) / hudScale));
		}

		if (config.showKeys) {
			renderKeys(graphics, client, (int) (posX(Overlay.KEYS, config, client, screenW) / hudScale),
					(int) (posY(Overlay.KEYS, config, client, screenH) / hudScale), false);
		}

		if (config.showArmor) {
			renderArmor(graphics, client, (int) (posX(Overlay.ARMOR, config, client, screenW) / hudScale),
					(int) (posY(Overlay.ARMOR, config, client, screenH) / hudScale));
		}

		if (config.showPing) {
			renderPing(graphics, client, (int) (posX(Overlay.PING, config, client, screenW) / hudScale),
					(int) (posY(Overlay.PING, config, client, screenH) / hudScale));
		}

		if (config.showCps) {
			renderCps(graphics, client, (int) (posX(Overlay.CPS, config, client, screenW) / hudScale),
					(int) (posY(Overlay.CPS, config, client, screenH) / hudScale));
		}

		graphics.pose().popMatrix();

		renderTargetHighlight(graphics, client);
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
		int base = switch (overlay) {
			case FPS -> fpsWidth(client);
			case KEYS -> widgetWidth();
			case ARMOR -> ARMOR_WIDTH;
			case PING -> pingWidth(client);
			case CPS -> cpsWidth(client);
		};
		return Math.max(1, Math.round(base * CubeonHudConfig.get().scale));
	}

	public static int heightOf(Overlay overlay, Minecraft client) {
		int base = switch (overlay) {
			case FPS -> fpsHeight(client);
			case KEYS -> widgetHeight();
			case ARMOR -> ARMOR_HEIGHT;
			case PING -> client.font.lineHeight + 3;
			case CPS -> cpsHeight(client);
		};
		return Math.max(1, Math.round(base * CubeonHudConfig.get().scale));
	}

	public static int widgetWidth() {
		return 3 * KEY_SIZE + 2 * GAP;
	}

	public static int widgetHeight() {
		return 3 * KEY_SIZE + 3 * GAP + SPACE_HEIGHT;
	}

	public static int posX(Overlay overlay, CubeonHudConfig config, Minecraft client, int screenW) {
		float fraction = switch (overlay) {
			case FPS -> config.fpsX;
			case KEYS -> config.keysX;
			case ARMOR -> config.armorX;
			case PING -> config.pingX;
			case CPS -> config.cpsX;
		};
		return Math.round(fraction * Math.max(0, screenW - widthOf(overlay, client)));
	}

	public static int posY(Overlay overlay, CubeonHudConfig config, Minecraft client, int screenH) {
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
	public static void moveTo(Overlay overlay, CubeonHudConfig config, Minecraft client,
			int x, int y, int screenW, int screenH) {
		int freeX = Math.max(0, screenW - widthOf(overlay, client));
		int freeY = Math.max(0, screenH - heightOf(overlay, client));
		float fractionX = freeX == 0 ? 0.0F : (float) x / freeX;
		float fractionY = freeY == 0 ? 0.0F : (float) y / freeY;

		switch (overlay) {
			case FPS -> {
				config.fpsX = CubeonHudConfig.clamp01(fractionX);
				config.fpsY = CubeonHudConfig.clamp01(fractionY);
			}
			case KEYS -> {
				config.keysX = CubeonHudConfig.clamp01(fractionX);
				config.keysY = CubeonHudConfig.clamp01(fractionY);
			}
			case ARMOR -> {
				config.armorX = CubeonHudConfig.clamp01(fractionX);
				config.armorY = CubeonHudConfig.clamp01(fractionY);
			}
			case PING -> {
				config.pingX = CubeonHudConfig.clamp01(fractionX);
				config.pingY = CubeonHudConfig.clamp01(fractionY);
			}
			case CPS -> {
				config.cpsX = CubeonHudConfig.clamp01(fractionX);
				config.cpsY = CubeonHudConfig.clamp01(fractionY);
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

		boolean[] showSlots = {
				CubeonHudConfig.get().showArmorHelmet,
				CubeonHudConfig.get().showArmorChest,
				CubeonHudConfig.get().showArmorLegs,
				CubeonHudConfig.get().showArmorFeet,
				CubeonHudConfig.get().showArmorMainHand,
				CubeonHudConfig.get().showArmorOffHand,
		};

		for (int i = 0; i < stacks.length; i++) {
			if (!showSlots[i]) {
				continue;
			}

			ItemStack stack = stacks[i];

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

	private static void renderTargetHighlight(GuiGraphicsExtractor graphics, Minecraft client) {
		if (client.player == null || client.hitResult == null) {
			return;
		}

		if (!(client.hitResult instanceof EntityHitResult hit)) {
			return;
		}

		if (!(hit.getEntity() instanceof Player target)) {
			return;
		}

		if (client.player.distanceTo(target) > client.player.entityInteractionRange() + 1.0D) {
			return;
		}

		AABB box = target.getBoundingBox();
		Vec3[] corners = {
				new Vec3(box.minX, box.minY, box.minZ),
				new Vec3(box.maxX, box.minY, box.minZ),
				new Vec3(box.minX, box.maxY, box.minZ),
				new Vec3(box.maxX, box.maxY, box.minZ),
				new Vec3(box.minX, box.minY, box.maxZ),
				new Vec3(box.maxX, box.minY, box.maxZ),
				new Vec3(box.minX, box.maxY, box.maxZ),
				new Vec3(box.maxX, box.maxY, box.maxZ),
		};

		float minX = Float.MAX_VALUE;
		float minY = Float.MAX_VALUE;
		float maxX = -Float.MAX_VALUE;
		float maxY = -Float.MAX_VALUE;

		for (Vec3 corner : corners) {
			Vec3 projected = client.gameRenderer.projectPointToScreen(corner);
			minX = Math.min(minX, (float) projected.x);
			minY = Math.min(minY, (float) projected.y);
			maxX = Math.max(maxX, (float) projected.x);
			maxY = Math.max(maxY, (float) projected.y);
		}

		if (minX == Float.MAX_VALUE) {
			return;
		}

		int x1 = (int) minX;
		int y1 = (int) minY;
		int x2 = (int) maxX;
		int y2 = (int) maxY;
		int color = 0xFFFF3333;

		graphics.fill(x1, y1, x2, y1 + 1, color);
		graphics.fill(x1, y2 - 1, x2, y2, color);
		graphics.fill(x1, y1, x1 + 1, y2, color);
		graphics.fill(x2 - 1, y1, x2, y2, color);

		int cx = graphics.guiWidth() / 2;
		int cy = graphics.guiHeight() / 2;
		graphics.fill(cx - 6, cy, cx + 6, cy + 1, color);
		graphics.fill(cx, cy - 6, cx + 1, cy + 6, color);
	}
}
