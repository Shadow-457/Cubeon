package com.cubeon.client;
import net.minecraft.text.Text;
import net.minecraft.text.Style;
import net.minecraft.util.Identifier;
import net.minecraft.text.StyleSpriteSource;

/** A font-scoped logo: server names keep their original font and styling. */
public final class TabLogo {
    private static final Style STYLE = Style.EMPTY.withFont(new StyleSpriteSource.Font(Identifier.tryParse("cubeon-client:cubeon_client")));
    private TabLogo() { }
    public static Text icon() { return Text.literal("\uE000").setStyle(STYLE); }
}
