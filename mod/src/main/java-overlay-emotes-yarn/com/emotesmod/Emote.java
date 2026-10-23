package com.emotesmod;

import net.minecraft.text.MutableText;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;
import net.minecraft.util.StringIdentifiable;

/**
 * The emote animations this mod knows about.
 *
 * <p>Every emote has a fixed duration in seconds. Once it has played the character
 * automatically returns to its normal pose, so there is no emote that can get stuck
 * "on" forever.
 */
public enum Emote implements StringIdentifiable {
	WAVE("wave", 3.0F, Formatting.YELLOW),
	DANCE("dance", 6.0F, Formatting.LIGHT_PURPLE),
	BOW("bow", 3.0F, Formatting.GRAY),
	SALUTE("salute", 3.0F, Formatting.GOLD),
	SHRUG("shrug", 2.5F, Formatting.WHITE),
	POINT("point", 3.0F, Formatting.AQUA);

	/** Sentinel meaning "stop whatever you are doing". Sent over the network as {@code -1}. */
	public static final int STOP_ID = -1;

	private static final Emote[] BY_ID = values();

	private final String name;
	private final float durationSeconds;
	private final Formatting color;

	Emote(String name, float durationSeconds, Formatting color) {
		this.name = name;
		this.durationSeconds = durationSeconds;
		this.color = color;
	}

	public String getName() {
		return this.name;
	}

	/** How long the emote lasts, in seconds. */
	public float durationSeconds() {
		return this.durationSeconds;
	}

	public Formatting color() {
		return this.color;
	}

	/** Stable id used on the wire. Do not reorder the constants without bumping the protocol. */
	public int id() {
		return this.ordinal();
	}

	public String translationKey() {
		return EmotesMod.MOD_ID + ".emote." + this.name;
	}

	public MutableText displayName() {
		return Text.translatable(this.translationKey());
	}

	/** A fresh, coloured instance. Safe to mutate because every call builds a new object. */
	public MutableText displayNameColored() {
		return Text.translatable(this.translationKey()).formatted(this.color);
	}

	@Override
	public String asString() {
		return this.name;
	}

	/** @return the emote with this id, or {@code null} if the id is out of range. */
	public static Emote byId(int id) {
		if (id < 0 || id >= BY_ID.length) {
			return null;
		}

		return BY_ID[id];
	}

	/** @return the emote with this name (case insensitive), or {@code null}. */
	public static Emote byName(String name) {
		for (Emote emote : BY_ID) {
			if (emote.name.equalsIgnoreCase(name)) {
				return emote;
			}
		}

		return null;
	}
}
