package com.cubeon.client;
import net.minecraft.text.Text;
import net.minecraft.text.Style;
import net.minecraft.util.Identifier;

/** A font-scoped logo: server names keep their original font and styling. */
public final class TabLogo {
    private static final Style STYLE = Style.EMPTY.withFont(Identifier.tryParse("cubeon-client:cubeon_client"));
    private TabLogo() { }
    public static Text icon() { return Text.literal("\uE000").setStyle(STYLE); }
}
