package com.cubeon.client;

import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.ChatComponent;
import net.minecraft.network.chat.Component;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

/**
 * Collapses repeated chat / game messages into a single line carrying a multiplier
 * ("hello" -> "hello (2x)" -> "hello (3x)") so spam no longer floods the chat HUD.
 */
public final class ChatCollapse {
	private static final long WINDOW_MS = 10000L;

	private static final Map<String, Integer> COUNTS = new HashMap<>();
	private static final Map<String, Long> LAST_SEEN = new HashMap<>();
	private static final Map<String, String> LAST_DISPLAYED = new HashMap<>();

	private ChatCollapse() {
	}

	public static void register() {
		ClientReceiveMessageEvents.ALLOW_CHAT.register((message, signedMessage, sender, params, receptionTimestamp) ->
				handle(message, false));
		ClientReceiveMessageEvents.ALLOW_GAME.register((message, overlay) -> handle(message, true));
	}

	private static boolean handle(Component message, boolean game) {
		String key = message.getString();
		long now = System.currentTimeMillis();
		Long lastTime = LAST_SEEN.get(key);
		Integer count = COUNTS.get(key);

		boolean duplicate = count != null && lastTime != null && now - lastTime < WINDOW_MS;

		if (!duplicate) {
			COUNTS.put(key, 1);
			LAST_SEEN.put(key, now);
			LAST_DISPLAYED.put(key, key);
			return true;
		}

		int newCount = count + 1;
		COUNTS.put(key, newCount);
		LAST_SEEN.put(key, now);

		String previousDisplayed = LAST_DISPLAYED.getOrDefault(key, key);
		String countedText = key + " (" + newCount + "x)";
		Component counted = message.copy().append(Component.literal(" (" + newCount + "x)"));

		removePrevious(previousDisplayed);
		LAST_DISPLAYED.put(key, counted.getString());

		Minecraft client = Minecraft.getInstance();

		if (client != null && client.gui != null) {
			ChatComponent chat = client.gui.getChat();

			if (game) {
				chat.addServerSystemMessage(counted);
			} else {
				chat.addPlayerMessage(counted, null, null);
			}
		}

		return false;
	}

	private static void removePrevious(String displayed) {
		Minecraft client = Minecraft.getInstance();

		if (client == null || client.gui == null) {
			return;
		}

		ChatComponent chat = client.gui.getChat();

		try {
			Field field = ChatComponent.class.getDeclaredField("allMessages");
			field.setAccessible(true);
			Object value = field.get(chat);

			if (value instanceof List<?> list) {
				Iterator<?> iterator = list.iterator();

				while (iterator.hasNext()) {
					Object entry = iterator.next();

					try {
						Method contentMethod = entry.getClass().getMethod("content");
						Object content = contentMethod.invoke(entry);

						if (content instanceof Component component && component.getString().equals(displayed)) {
							iterator.remove();
						}
					} catch (Throwable ignored) {
					}
				}
			}

			Method refresh = ChatComponent.class.getDeclaredMethod("refreshTrimmedMessages");
			refresh.setAccessible(true);
			refresh.invoke(chat);
		} catch (Throwable ignored) {
		}
	}
}
