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
		CPS, CLOCK, SYSTEM, POTIONS, COORDINATES, DIRECTION, BIOME, DAYLIGHT, COMBO
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
		HudElementRegistry.addLast(Identifier.fromNamespaceAndPath(CubeonHudClient.MOD_ID, "overlays"), CubeonHud::render);
	}

	private static void render(GuiGraphicsExtractor graphics, DeltaTracker deltaTracker) {
		Minecraft client = Minecraft.getInstance();

		if (client.player == null) {
			return;
		}

		sampleClicks(client);

		// Debug tools (F3/F3+B) keep the HUD visible. F1 still hides it,
		// and the position editor draws its own live ghost instead.
		if (client.options.hideGui || client.screen instanceof MoveOverlayScreen) {
			return;
		}

		CubeonHudConfig config = CubeonHudConfig.get();
		int screenW = graphics.guiWidth();
		int screenH = graphics.guiHeight();

		if (config.showFps) {
			renderOverlay(graphics, client, config, Overlay.FPS, screenW, screenH, CubeonHud::renderFps);
		}

		if (config.showKeys) {
			renderOverlay(graphics, client, config, Overlay.KEYS, screenW, screenH,
					(drawContext, minecraftClient, x, y) -> renderKeys(drawContext, minecraftClient, x, y, false));
		}

		if (config.showArmor) {
			renderOverlay(graphics, client, config, Overlay.ARMOR, screenW, screenH, CubeonHud::renderArmor);
		}

		if (config.showPing) {
			renderOverlay(graphics, client, config, Overlay.PING, screenW, screenH, CubeonHud::renderPing);
		}

		if (config.showCps) {
			renderOverlay(graphics, client, config, Overlay.CPS, screenW, screenH, CubeonHud::renderCps);
		}

        if (config.extrasEnabled()) {
            for (Overlay overlay : Overlay.values()) if (overlay.ordinal() >= 5 && config.extraEnabled(slotOf(overlay)))
                renderOverlay(graphics, client, config, overlay, screenW, screenH,
                        (draw, mc, x, y) -> renderExtra(draw, mc, overlay, x, y, false));
        }

        com.cubeon.client.hud.screen.FriendsToastRenderer.render(graphics, client, screenW, screenH);

		EnemyHealthRenderer.render(graphics, client, deltaTracker.getGameTimeDeltaPartialTick(false),
				client.screen == null && !client.options.hideGui, client.gameRenderer.getMainCamera().rotation(), client.gameRenderer.getMainCamera().position());
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
			default -> ExtraHud.width(HudFeatures.at(overlay.ordinal()), client.font::width);
		};
		return Math.max(1, Math.round(base * CubeonHud.scaleOf(overlay)));
	}

	public static int heightOf(Overlay overlay, Minecraft client) {
		int base = switch (overlay) {
			case FPS -> fpsHeight(client);
			case KEYS -> widgetHeight();
			case ARMOR -> ARMOR_HEIGHT;
			case PING -> client.font.lineHeight + 3;
			case CPS -> cpsHeight(client);
			default -> ExtraHud.height(HudFeatures.at(overlay.ordinal()));
		};
		return Math.max(1, Math.round(base * CubeonHud.scaleOf(overlay)));
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
			default -> config.extra(slotOf(overlay)).x;
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
			default -> config.extra(slotOf(overlay)).y;
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
			default -> {
                var value = config.extra(slotOf(overlay));
                value.x = CubeonHudConfig.clamp01(fractionX); value.y = CubeonHudConfig.clamp01(fractionY);
            }
		}
	}

	/**
	 * Draws one overlay at its own size. A single transform around the whole HUD
	 * cannot work any more: each overlay has a size of its own
	 * ({@link CubeonHudConfig#scaleFor(String)}), so its pixels are scaled and
	 * its screen position is divided by that same scale.
	 */
	private static void renderOverlay(GuiGraphicsExtractor graphics, Minecraft client, CubeonHudConfig config,
			Overlay overlay, int screenW, int screenH, OverlayRenderer renderer) {
		float scale = config.scaleFor(slotOf(overlay));
		graphics.pose().pushMatrix();
		graphics.pose().scale(scale, scale);
		renderer.render(graphics, client,
				Math.round(posX(overlay, config, client, screenW) / scale),
				Math.round(posY(overlay, config, client, screenH) / scale));
		graphics.pose().popMatrix();
	}

	/** Enabled overlays are previewed without changing the player's visibility choices. */
    public static boolean enabled(Overlay overlay, CubeonHudConfig config) {
        return switch (overlay) {
            case FPS -> config.showFps; case KEYS -> config.showKeys;
            case ARMOR -> config.showArmor; case PING -> config.showPing; case CPS -> config.showCps;
            default -> config.extraEnabled(slotOf(overlay));
        };
    }
    public static void renderPreview(GuiGraphicsExtractor graphics, Minecraft client, CubeonHudConfig config,
                                     Overlay overlay, int screenW, int screenH) {
        OverlayRenderer renderer = switch (overlay) {
            case FPS -> CubeonHud::renderFps;
            case KEYS -> (d,c,x,y) -> renderKeys(d,c,x,y,true);
            case ARMOR -> CubeonHud::renderArmor;
            case PING -> CubeonHud::renderPing;
            case CPS -> CubeonHud::renderCps;
            default -> (d,c,x,y) -> renderExtra(d,c,overlay,x,y,true);
        };
        renderOverlay(graphics,client,config,overlay,screenW,screenH,renderer);
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
			default -> HudFeatures.at(overlay.ordinal()).slot;
		};
	}

	@FunctionalInterface
	private interface OverlayRenderer {
		void render(GuiGraphicsExtractor graphics, Minecraft client, int x, int y);
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

    /** Names and bars share the projected label plane, including walking/hurt tilt. */
    private static void applyEnemyPose(GuiGraphicsExtractor graphics, EnemyHealthBar.Pose pose) {
        graphics.pose().mul(new org.joml.Matrix3x2f(pose.rightX(), pose.rightY(),
                pose.downX(), pose.downY(), pose.originX(), pose.originY()));
    }

    public static void drawEnemyName(GuiGraphicsExtractor graphics, Minecraft client, net.minecraft.network.chat.Component label,
                                     EnemyHealthBar.Pose pose) {
        graphics.pose().pushMatrix();
        try {
            applyEnemyPose(graphics, pose);
            graphics.text(client.font, label, -client.font.width(label) / 2, 0, 0xFFE4E7EB, true);
        } finally {
            graphics.pose().popMatrix();
        }
    }

    public static void drawEnemyBar(GuiGraphicsExtractor graphics, Minecraft client,
                                    EnemyHealthBar.Pose pose, int hearts) {
        graphics.pose().pushMatrix();
        try {
            applyEnemyPose(graphics, pose);
            EnemyHealthBar.drawLocal((x, y, right, bottom, color) ->
                    fillEnemyRect(graphics, x, y, right, bottom, color), hearts);
            graphics.text(client.font, Integer.toString(hearts), Math.round(EnemyHealthBar.numberX(hearts)),
                    EnemyHealthBar.TOP, 0xFFE4E7EB, true);
        } finally {
            graphics.pose().popMatrix();
        }
    }

    /** Unit quads keep health-bar coordinates fractional until native rasterization. */
    public static void fillEnemyRect(GuiGraphicsExtractor graphics, float x, float y, float right, float bottom, int color) {
        graphics.pose().pushMatrix();
        try {
            graphics.pose().translate(x, y);
            graphics.pose().scale(right - x, bottom - y);
            graphics.fill(0, 0, 1, 1, color);
        } finally {
            graphics.pose().popMatrix();
        }
    }

    public static boolean screenOpen() { var client = Minecraft.getInstance(); return client.screen != null; }
    public static boolean hudHidden() { var client = Minecraft.getInstance(); return client.options.hideGui; }
    public static void renderExtra(GuiGraphicsExtractor context, Minecraft client, Overlay overlay, int x, int y, boolean preview) {
        ExtraHud.render(extraCanvas(context, client), HudFeatures.at(overlay.ordinal()), x, y, preview);
        if (overlay == Overlay.POTIONS) for (int i = 0; i < ExtraHud.effects().size(); i++) {
            if (ExtraHud.effects().get(i).icon() instanceof net.minecraft.resources.Identifier icon) { context.blitSprite(net.minecraft.client.renderer.RenderPipelines.GUI_TEXTURED, icon, x + 2, y + 1 + i * 12, 10, 10); }
        }
    }
    private static com.cubeon.client.ui.ClientUi.Canvas extraCanvas(GuiGraphicsExtractor context, Minecraft client) {
        return new com.cubeon.client.ui.ClientUi.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { context.fill(x0, y0, x1, y1, color); }
            public void text(String value, int centerX, int y, int color) { context.text(client.font, value, centerX - client.font.width(value) / 2, y, color, true); }
            public int width(String value) { return client.font.width(value); }
            public String translate(String key) { return net.minecraft.network.chat.Component.translatable(key).getString(); }
        };
    }
}
