package com.emotesmod;

import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.context.CommandContext;
import com.mojang.brigadier.suggestion.SuggestionProvider;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.commands.arguments.EntityArgument;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Locale;

/**
 * The {@code /emote} command.
 *
 * <pre>
 *   /emote                          list the available emotes
 *   /emote stop                     stop your own emote
 *   /emote wave                     play "wave" on yourself
 *   /emote dance Alex Steve         play "dance" on other players (gamemasters only)
 * </pre>
 */
public final class EmoteCommand {
	private static final List<String> SUGGESTIONS = buildSuggestions();

	private static final SuggestionProvider<CommandSourceStack> EMOTE_SUGGESTIONS =
			(context, builder) -> {
				String prefix = builder.getRemaining().toLowerCase(Locale.ROOT);

				for (String option : SUGGESTIONS) {
					if (option.startsWith(prefix)) {
						builder.suggest(option);
					}
				}

				return builder.buildFuture();
			};

	private EmoteCommand() {
	}

	/** Call once from the common initializer. */
	public static void register() {
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
				Commands.literal("emote")
						.executes(EmoteCommand::listEmotes)
						.then(Commands.literal("stop").executes(EmoteCommand::stopSelf))
						.then(Commands.literal("list").executes(EmoteCommand::listEmotes))
						.then(Commands.argument("emote", StringArgumentType.word())
								.suggests(EMOTE_SUGGESTIONS)
								.executes(context -> playSelf(context, StringArgumentType.getString(context, "emote")))
								.then(Commands.argument("targets", EntityArgument.players())
										.requires(Commands.hasPermission(Commands.LEVEL_GAMEMASTERS))
										.executes(context -> playOthers(
												context,
												StringArgumentType.getString(context, "emote"),
												EntityArgument.getPlayers(context, "targets")))))));
	}

	private static List<String> buildSuggestions() {
		List<String> list = new ArrayList<>();
		list.add(EmotesMod.STOP_COMMAND);
		list.add("list");

		for (Emote emote : Emote.values()) {
			list.add(emote.getName());
		}

		return List.copyOf(list);
	}

	private static int listEmotes(CommandContext<CommandSourceStack> context) {
		CommandSourceStack source = context.getSource();
		source.sendSuccess(() -> Component.translatable(EmotesMod.MOD_ID + ".command.list"), false);

		for (Emote emote : Emote.values()) {
			source.sendSuccess(() -> Component.translatable(EmotesMod.MOD_ID + ".command.list.entry",
					emote.displayNameColored(), emote.getName()), false);
		}

		return Emote.values().length;
	}

	private static int stopSelf(CommandContext<CommandSourceStack> context) {
		CommandSourceStack source = context.getSource();
		ServerPlayer player = source.getPlayer();

		if (player == null) {
			source.sendFailure(Component.translatable(EmotesMod.MOD_ID + ".command.not_player"));
			return 0;
		}

		EmoteNetworking.stopFor(player);
		source.sendSuccess(() -> Component.translatable(EmotesMod.MOD_ID + ".command.stopped"), true);
		return 1;
	}

	private static int playSelf(CommandContext<CommandSourceStack> context, String name) {
		CommandSourceStack source = context.getSource();
		Emote emote = Emote.byName(name);

		if (emote == null) {
			source.sendFailure(Component.translatable(EmotesMod.MOD_ID + ".command.unknown", name));
			return 0;
		}

		ServerPlayer player = source.getPlayer();

		if (player == null) {
			source.sendFailure(Component.translatable(EmotesMod.MOD_ID + ".command.not_player"));
			return 0;
		}

		EmoteNetworking.playFor(player, emote, 0);
		source.sendSuccess(() -> Component.translatable(EmotesMod.MOD_ID + ".command.played", emote.displayNameColored()), true);
		return 1;
	}

	private static int playOthers(CommandContext<CommandSourceStack> context, String name,
			Collection<ServerPlayer> targets) {
		CommandSourceStack source = context.getSource();
		Emote emote = Emote.byName(name);

		if (emote == null) {
			source.sendFailure(Component.translatable(EmotesMod.MOD_ID + ".command.unknown", name));
			return 0;
		}

		int count = 0;

		for (ServerPlayer target : targets) {
			if (EmoteNetworking.playFor(target, emote, 0)) {
				count++;
			}
		}

		final int played = count;
		source.sendSuccess(() -> Component.translatable(EmotesMod.MOD_ID + ".command.played_others",
				emote.displayNameColored(), played), true);
		return played;
	}
}
