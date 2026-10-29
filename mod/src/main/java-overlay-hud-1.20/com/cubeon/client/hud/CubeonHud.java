package com.cubeon.client.hud;

import com.cubeon.client.hud.screen.MoveOverlayScreen;
import net.fabricmc.fabric.api.client.rendering.v1.HudRenderCallback;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.entity.EquipmentSlot;
import net.minecraft.item.ItemStack;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.util.hit.EntityHitResult;
import net.minecraft.util.hit.HitResult;
import net.minecraft.util.math.Box;
import net.minecraft.util.math.Vec3d;

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
	// layout used by the usual PvP clients - helmet, chestplate, leggings, boots.
	// Only worn, damageable items get a row; empty slots are simply skipped. The
	// held item and offhand deliberately have no row (2026-10-28): their durability
	// is already on the hotbar, and this HUD is about armour.
	static final int ARMOR_ICON_SIZE = 16;
	static final int ARMOR_ROW_HEIGHT = 16;
	static final int ARMOR_SLOTS = 4;
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
		LegacyHealthProjection.register();
		// 1.20.0 predates HudElementRegistry; the older event-based callback is used instead.
		HudRenderCallback.EVENT.register((context, tickDelta) -> render(context));
	}

	private static void render(DrawContext context) {
		MinecraftClient client = MinecraftClient.getInstance();

		if (client.player == null) {
			return;
		}

		sampleClicks(client);

		// While the position editor is open it draws its own live ghost instead.
		if (client.options.debugEnabled) {
			return;
		}

		if (client.options.hudHidden || client.currentScreen instanceof MoveOverlayScreen) {
			return;
		}

		CubeonHudConfig config = CubeonHudConfig.get();
		int screenW = context.getScaledWindowWidth();
		int screenH = context.getScaledWindowHeight();

		if (config.showFps) {
			renderOverlay(context, client, config, Overlay.FPS, screenW, screenH, CubeonHud::renderFps);
		}

		if (config.showKeys) {
			renderOverlay(context, client, config, Overlay.KEYS, screenW, screenH,
					(drawContext, minecraftClient, x, y) -> renderKeys(drawContext, minecraftClient, x, y, false));
		}

		if (config.showArmor) {
			renderOverlay(context, client, config, Overlay.ARMOR, screenW, screenH, CubeonHud::renderArmor);
		}

		if (config.showPing) {
			renderOverlay(context, client, config, Overlay.PING, screenW, screenH, CubeonHud::renderPing);
		}

		if (config.showCps) {
			renderOverlay(context, client, config, Overlay.CPS, screenW, screenH, CubeonHud::renderCps);
		}

		LegacyHealthProjection.render(context, client);
	}

	/** Counts press edges of the attack/use bindings once per frame. */
	private static void sampleClicks(MinecraftClient client) {
		boolean attack = client.options.attackKey.isPressed();
		boolean use = client.options.useKey.isPressed();
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

	public static int widthOf(Overlay overlay, MinecraftClient client) {
		int base = switch (overlay) {
			case FPS -> fpsWidth(client);
			case KEYS -> widgetWidth();
			case ARMOR -> ARMOR_WIDTH;
			case PING -> pingWidth(client);
			case CPS -> cpsWidth(client);
		};
		return Math.max(1, Math.round(base * CubeonHud.scaleOf(overlay)));
	}

	public static int heightOf(Overlay overlay, MinecraftClient client) {
		int base = switch (overlay) {
			case FPS -> fpsHeight(client);
			case KEYS -> widgetHeight();
			case ARMOR -> ARMOR_HEIGHT;
			case PING -> client.textRenderer.fontHeight + 3;
			case CPS -> cpsHeight(client);
		};
		return Math.max(1, Math.round(base * CubeonHud.scaleOf(overlay)));
	}

	public static int widgetWidth() {
		return 3 * KEY_SIZE + 2 * GAP;
	}

	public static int widgetHeight() {
		return 3 * KEY_SIZE + 3 * GAP + SPACE_HEIGHT;
	}

	public static int posX(Overlay overlay, CubeonHudConfig config, MinecraftClient client, int screenW) {
		float fraction = switch (overlay) {
			case FPS -> config.fpsX;
			case KEYS -> config.keysX;
			case ARMOR -> config.armorX;
			case PING -> config.pingX;
			case CPS -> config.cpsX;
		};
		return Math.round(fraction * Math.max(0, screenW - widthOf(overlay, client)));
	}

	public static int posY(Overlay overlay, CubeonHudConfig config, MinecraftClient client, int screenH) {
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
	public static void moveTo(Overlay overlay, CubeonHudConfig config, MinecraftClient client,
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

	/**
	 * Draws one overlay at its own size. A single transform around the whole HUD
	 * cannot work any more: each overlay has a size of its own
	 * ({@link CubeonHudConfig#scaleFor(String)}), so its pixels are scaled and
	 * its screen position is divided by that same scale.
	 */
	private static void renderOverlay(DrawContext context, MinecraftClient client, CubeonHudConfig config,
			Overlay overlay, int screenW, int screenH, OverlayRenderer renderer) {
		float scale = config.scaleFor(slotOf(overlay));
		context.getMatrices().push();
		context.getMatrices().scale(scale, scale, 1.0F);
		renderer.render(context, client,
				Math.round(posX(overlay, config, client, screenW) / scale),
				Math.round(posY(overlay, config, client, screenH) / scale));
		context.getMatrices().pop();
	}

	/** One overlay's saved size, including the legacy shared-size fallback. */
	public static float scaleOf(Overlay overlay) {
		return CubeonHudConfig.get().scaleFor(slotOf(overlay));
	}

	/** The config slot name of an overlay ("fps", "keys", ...). */
	public static String slotOf(Overlay overlay) {
		return switch (overlay) {
			case FPS -> "fps";
			case KEYS -> "keys";
			case ARMOR -> "armor";
			case PING -> "ping";
			case CPS -> "cps";
		};
	}

	@FunctionalInterface
	private interface OverlayRenderer {
		void render(DrawContext context, MinecraftClient client, int x, int y);
	}

	// ------------------------------------------------------------------------ drawing

	public static void renderFps(DrawContext context, MinecraftClient client, int x, int y) {
		String text = client.getCurrentFps() + " FPS";
		int textWidth = client.textRenderer.getWidth(text);

		context.fill(x, y, x + textWidth + 4, y + fpsHeight(client), FPS_BACKGROUND);
		context.drawTextWithShadow(client.textRenderer, text, x + 2, y + 1, 0xFFFFFFFF);
	}

	public static void renderKeys(DrawContext context, MinecraftClient client, int x, int y, boolean preview) {
		int secondRowY = y + KEY_SIZE + GAP;
		int thirdRowY = y + 2 * (KEY_SIZE + GAP);

		// W sits centred above the A S D row; held keys light up green.
		keyBox(context, client, x + KEY_SIZE + GAP, y, KEY_SIZE, KEY_SIZE, "W",
				preview || client.options.forwardKey.isPressed());
		keyBox(context, client, x, secondRowY, KEY_SIZE, KEY_SIZE, "A",
				preview || client.options.leftKey.isPressed());
		keyBox(context, client, x + KEY_SIZE + GAP, secondRowY, KEY_SIZE, KEY_SIZE, "S",
				preview || client.options.backKey.isPressed());
		keyBox(context, client, x + 2 * (KEY_SIZE + GAP), secondRowY, KEY_SIZE, KEY_SIZE, "D",
				preview || client.options.rightKey.isPressed());

		keyBox(context, client, x, thirdRowY, MOUSE_BUTTON_WIDTH, KEY_SIZE, "LMB",
				preview || client.options.attackKey.isPressed());
		keyBox(context, client, x + MOUSE_BUTTON_WIDTH + GAP, thirdRowY, MOUSE_BUTTON_WIDTH, KEY_SIZE, "RMB",
				preview || client.options.useKey.isPressed());

		spaceBar(context, x, y + 3 * (KEY_SIZE + GAP), widgetWidth(), preview || client.options.jumpKey.isPressed());
	}

	public static void renderArmor(DrawContext context, MinecraftClient client, int x, int y) {
		if (client.player == null) {
			return;
		}

		var player = client.player;
		ItemStack[] stacks = {
				player.getEquippedStack(EquipmentSlot.HEAD),
				player.getEquippedStack(EquipmentSlot.CHEST),
				player.getEquippedStack(EquipmentSlot.LEGS),
				player.getEquippedStack(EquipmentSlot.FEET),
		};

		int row = 0;

		boolean[] showSlots = {
				CubeonHudConfig.get().showArmorHelmet,
				CubeonHudConfig.get().showArmorChest,
				CubeonHudConfig.get().showArmorLegs,
				CubeonHudConfig.get().showArmorFeet,
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
			context.drawItem(stack, x, rowY);

			// Remaining uses, the number shown next to the icon.
			int remaining = stack.getMaxDamage() - stack.getDamage();
			context.drawTextWithShadow(client.textRenderer, String.valueOf(remaining),
					x + ARMOR_ICON_SIZE + 3, rowY + 4, 0xFFFFFFFF);
			row++;
		}
	}

	public static void renderPing(DrawContext context, MinecraftClient client, int x, int y) {
		String text;
		int color;

		var handler = client.getNetworkHandler();
		var entry = handler == null || client.player == null ? null : handler.getPlayerListEntry(client.player.getUuid());

		if (entry == null) {
			text = "Ping: --";
			color = DIM_TEXT;
		} else {
			int latency = entry.getLatency();
			text = "Ping: " + latency + " ms";
			color = latency <= 60 ? COLOR_GOOD : latency <= 130 ? COLOR_OK : COLOR_BAD;
		}

		context.fill(x, y, x + pingWidth(client), y + client.textRenderer.fontHeight + 3, FPS_BACKGROUND);
		context.drawTextWithShadow(client.textRenderer, text, x + 2, y + 1, color);
	}

	public static void renderCps(DrawContext context, MinecraftClient client, int x, int y) {
		int lineHeight = client.textRenderer.fontHeight + 2;

		context.fill(x, y, x + cpsWidth(client), y + cpsHeight(client), FPS_BACKGROUND);
		context.drawTextWithShadow(client.textRenderer, "LMB: " + LEFT_CLICKS.size() + " CPS", x + 2, y + 1, 0xFFFFFFFF);
		context.drawTextWithShadow(client.textRenderer, "RMB: " + RIGHT_CLICKS.size() + " CPS", x + 2, y + lineHeight + 1, 0xFFFFFFFF);
	}

	public static void drawOutline(DrawContext context, int x, int y, int width, int height, int color) {
		context.fill(x, y, x + width, y + 1, color);
		context.fill(x, y + height - 1, x + width, y + height, color);
		context.fill(x, y, x + 1, y + height, color);
		context.fill(x + width - 1, y, x + width, y + height, color);
	}

	private static int fpsWidth(MinecraftClient client) {
		return client.textRenderer.getWidth(client.getCurrentFps() + " FPS") + 4;
	}

	private static int fpsHeight(MinecraftClient client) {
		return client.textRenderer.fontHeight + 3;
	}

	private static int pingWidth(MinecraftClient client) {
		return client.textRenderer.getWidth("Ping: 9999 ms") + 4;
	}

	private static int cpsWidth(MinecraftClient client) {
		return client.textRenderer.getWidth("LMB: 99 CPS") + 4;
	}

	private static int cpsHeight(MinecraftClient client) {
		return 2 * (client.textRenderer.fontHeight + 2) + 2;
	}




	private static void keyBox(DrawContext context, MinecraftClient client, int x, int y,
			int width, int height, String label, boolean down) {
		context.fill(x, y, x + width, y + height, down ? BOX_BACKGROUND_DOWN : BOX_BACKGROUND);
		drawOutline(context, x, y, width, height, down ? BOX_BORDER_DOWN : BOX_BORDER);

		var textRenderer = client.textRenderer;
		int textX = x + (width - textRenderer.getWidth(label)) / 2;
		int textY = y + (height - textRenderer.fontHeight) / 2;
		context.drawTextWithShadow(textRenderer, label, textX, textY, down ? KEY_TEXT_DOWN : KEY_TEXT);
	}

	private static void spaceBar(DrawContext context, int x, int y, int width, boolean down) {
		context.fill(x, y, x + width, y + SPACE_HEIGHT, down ? BOX_BACKGROUND_DOWN : BOX_BACKGROUND);
		drawOutline(context, x, y, width, SPACE_HEIGHT, down ? BOX_BORDER_DOWN : BOX_BORDER);

		// The little dash in the middle, like the usual keystrokes mods draw.
		int dashX = x + width / 2 - 5;
		int dashY = y + SPACE_HEIGHT / 2;
		context.fill(dashX, dashY, dashX + 10, dashY + 1, down ? KEY_TEXT_DOWN : KEY_TEXT);
	}


    /** Mob labels use the same projected scale as vanilla player name tags. */
    public static void drawEnemyName(DrawContext context, MinecraftClient client, net.minecraft.text.Text label,
                                     int center, int top, float scale) {
        context.getMatrices().push();
        try {
            context.getMatrices().scale(scale, scale, 1.0F);
            context.drawTextWithShadow(client.textRenderer, label,
                Math.round(center / scale) - client.textRenderer.getWidth(label) / 2,
                Math.round(top / scale), 0xFFE4E7EB);
        } finally {
            context.getMatrices().pop();
        }
    }
}
