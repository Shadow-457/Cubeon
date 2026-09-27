package com.cubeon.client;

import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.FontDescription;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.network.chat.Style;
import net.minecraft.network.chat.TextColor;
import net.minecraft.resources.Identifier;

/**
 * The 26.x build of the Friends corner button's label.
 *
 * <p>This class exists once per Minecraft era with the same FQN and the same
 * {@link #label(int)} entry point; the shared screen code never mentions an
 * era-specific type. Here, Minecraft 26 renamed {@code ResourceLocation} to
 * {@code Identifier} and moved font styling from {@code ResourceLocation} to
 * {@code FontDescription}, so the glyph is spelled out with the 26 names.
 * Only the bracket this file is compiled into sees it.
 *
 * <p>The button always shows the two-person glyph (the point of the icon - the
 * button used to be a blank square); when there are unanswered invites or
 * incoming requests their count is appended. Grass green {@code #83C13D}, the
 * Cubeon accent, drawn through Minecraft's bitmap font: the texture is an
 * alpha mask of the two-person shape and the text colour supplies the green.
 *
 * <p>Compiled only by the 26 bracket's build (overlay source dir added in
 * mod/build.gradle and tools/build_mod_jars.py), never against the shared API
 * stub - it uses the 26-only {@code FontDescription} chain by design.
 */
public final class CornerIcon {

    private static final Identifier FONT = Identifier.fromNamespaceAndPath(
            "cubeon-client", "cubeon_client");
    private static final Style GREEN = Style.EMPTY
            .withFont(new FontDescription.Resource(FONT))
            .withColor(TextColor.fromRgb(0x83C13D));
    private static final String GLYPH = "\uE000";

    private CornerIcon() {
    }

    public static Component label(int pending) {
        MutableComponent out = Component.literal(GLYPH).withStyle(GREEN);
        if (pending > 0) {
            // No space: the glyph's cell already ends in an empty column, and a
            // two-digit count would otherwise push the label past the 20px
            // button. An overflow of a stray third digit is not worth crowding.
            out = out.append(Component.literal(String.valueOf(pending)).withStyle(GREEN));
        }
        return out;
    }
}
