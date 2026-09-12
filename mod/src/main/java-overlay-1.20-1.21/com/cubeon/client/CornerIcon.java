package com.cubeon.client;

import net.minecraft.ChatFormatting;
import net.minecraft.network.chat.Component;

/**
 * The 1.20-1.21 build of the Friends corner button's label.
 *
 * <p>Sister class to the 26.x {@code CornerIcon}: same FQN, same
 * {@link #label(int)} entry point, compiled only by this bracket. Minecraft
 * 1.20-1.21 spans several component/font API generations internally
 * ({@code Style.withFont(ResourceLocation)} until ~1.21.5, the new
 * {@code FontDescription} chain by 1.21.11), so no single pre-26 jar can draw
 * the custom glyph on every version it serves. Until that bracket is split the
 * corner button here keeps its previous behaviour exactly - blank, or the
 * pending count as plain text when there is something actionable. Only
 * {@link Component}'s literal/empty factories are touched, which is the one
 * text path that has not moved across this whole range.
 *
 * <p>Compiled only by this bracket's Gradle/Loom build (overlay source dir
 * added in mod/build.gradle) and by the shared API stub in
 * tools/test_mod_compile.py, which is what keeps it on the version-stable
 * subset.
 */
public final class CornerIcon {

    /**
     * The nametag badge: a grey-bracketed Cubeon square in front of the name,
     * {@code [#]Shadow}. Written as an escape so the glyph survives any editor
     * or build that is careless about encodings.
     *
     * <p>Plain text rather than the mod's own font glyph, unlike the 26.x copy:
     * this bracket spans several font-API generations (see the class javadoc), so
     * a custom font here would render as a missing glyph on some of the versions
     * it serves. U+25A0 comes out of Minecraft's bundled unifont provider, which
     * every version in this range has.
     */
    private static final String MARK = "\u25A0";

    private CornerIcon() {
    }

    public static Component label(int pending) {
        return pending > 0 ? Component.literal(String.valueOf(pending)) : Component.empty();
    }

    /** The badge drawn in front of a Cubeon player's name. */
    public static Component badge() {
        return Component.empty()
                .append(Component.literal("[").withStyle(ChatFormatting.GRAY))
                .append(Component.literal(MARK).withStyle(ChatFormatting.GREEN))
                .append(Component.literal("]").withStyle(ChatFormatting.GRAY));
    }
}
