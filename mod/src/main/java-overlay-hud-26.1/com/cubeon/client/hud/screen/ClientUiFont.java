package com.cubeon.client.hud.screen;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.Style;
import net.minecraft.network.chat.FontDescription;
import net.minecraft.resources.Identifier;

/** Custom screen typography; gameplay HUD and resource-pack defaults remain independent. */
final class ClientUiFont {
    private static final Style STYLE = Style.EMPTY.withFont(new FontDescription.Resource(Identifier.fromNamespaceAndPath("cubeon-client", "ui")));
    private ClientUiFont() { }
    static Component text(String value) { return Component.literal(value).setStyle(STYLE); }
}
