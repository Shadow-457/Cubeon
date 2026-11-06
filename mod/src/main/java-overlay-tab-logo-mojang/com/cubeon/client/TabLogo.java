package com.cubeon.client;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.Style;
import net.minecraft.network.chat.FontDescription;
import net.minecraft.resources.Identifier;

/** A font-scoped logo: server names keep their original font and styling. */
public final class TabLogo {
    private static final Style STYLE = Style.EMPTY.withFont(new FontDescription.Resource(Identifier.parse("cubeon-client:cubeon_client")));
    private TabLogo() { }
    public static Component icon() { return Component.literal("\uE000").withStyle(STYLE); }
}
