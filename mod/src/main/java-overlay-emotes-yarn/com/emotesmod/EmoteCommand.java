package com.emotesmod;

import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.context.CommandContext;
import com.mojang.brigadier.suggestion.SuggestionProvider;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.command.argument.EntityArgumentType;
import net.minecraft.server.command.CommandManager;
import net.minecraft.server.command.ServerCommandSource;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.text.Text;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

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

	private EmoteCommand() {
	}

	/** Call once from the common initializer. */
	public static void register() {
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
				CommandManager.literal("emote")
						.executes(EmoteCommand::listEmotes)
						.then(CommandManager.literal("stop").executes(EmoteCommand::stopSelf))
						.then(CommandManager.literal("list").executes(EmoteCommand::listEmotes))
						.then(CommandManager.argument("emote", StringArgumentType.word())
								.suggests(EMOTE_SUGGESTIONS)
								.executes(context -> playSelf(context, StringArgumentType.getString(context, "emote")))
								.then(CommandManager.argument("targets", EntityArgumentType.players())
										.requires(source -> CommandManager.GAMEMASTERS_CHECK.allows(source.getPermissions()))
										.executes(context -> playOthers(
												context,
												StringArgumentType.getString(context, "emote"),
												EntityArgumentType.getPlayers(context, "targets")))))));
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

	private static final SuggestionProvider<ServerCommandSource> EMOTE_SUGGESTIONS =
			(context, builder) -> {
				String prefix = builder.getRemaining().toLowerCase(java.util.Locale.ROOT);

				for (String option : SUGGESTIONS) {
					if (option.startsWith(prefix)) {
						builder.suggest(option);
					}
				}

				return builder.buildFuture();
			};

	private static int listEmotes(CommandContext<ServerCommandSource> context) {
		ServerCommandSource source = context.getSource();
		source.sendFeedback(() -> Text.translatable(EmotesMod.MOD_ID + ".command.list"), false);

		for (Emote emote : Emote.values()) {
			source.sendFeedback(() -> Text.translatable(EmotesMod.MOD_ID + ".command.list.entry",
					emote.displayNameColored(), emote.getName()), false);
		}

		return Emote.values().length;
	}

	private static int stopSelf(CommandContext<ServerCommandSource> context) {
		ServerCommandSource source = context.getSource();
		ServerPlayerEntity player = source.getPlayer();

		if (player == null) {
			source.sendError(Text.translatable(EmotesMod.MOD_ID + ".command.not_player"));
			return 0;
		}

		EmoteNetworking.stopFor(player);
		source.sendFeedback(() -> Text.translatable(EmotesMod.MOD_ID + ".command.stopped"), true);
		return 1;
	}

	private static int playSelf(CommandContext<ServerCommandSource> context, String name) {
		ServerCommandSource source = context.getSource();
		Emote emote = Emote.byName(name);

		if (emote == null) {
			source.sendError(Text.translatable(EmotesMod.MOD_ID + ".command.unknown", name));
			return 0;
		}

		ServerPlayerEntity player = source.getPlayer();

		if (player == null) {
			source.sendError(Text.translatable(EmotesMod.MOD_ID + ".command.not_player"));
			return 0;
		}

		EmoteNetworking.playFor(player, emote, 0);
		source.sendFeedback(() -> Text.translatable(EmotesMod.MOD_ID + ".command.played", emote.displayNameColored()), true);
		return 1;
	}

	private static int playOthers(CommandContext<ServerCommandSource> context, String name,
			Collection<ServerPlayerEntity> targets) {
		ServerCommandSource source = context.getSource();
		Emote emote = Emote.byName(name);

		if (emote == null) {
			source.sendError(Text.translatable(EmotesMod.MOD_ID + ".command.unknown", name));
			return 0;
		}

		int count = 0;

		for (ServerPlayerEntity target : targets) {
			if (EmoteNetworking.playFor(target, emote, 0)) {
				count++;
			}
		}

		final int played = count;
		source.sendFeedback(() -> Text.translatable(EmotesMod.MOD_ID + ".command.played_others",
				emote.displayNameColored(), played), true);
		return played;
	}
}
