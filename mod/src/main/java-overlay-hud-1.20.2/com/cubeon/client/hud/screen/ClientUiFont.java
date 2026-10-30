package com.cubeon.client.hud.screen;
import net.minecraft.text.Text;
import net.minecraft.text.Style;
import net.minecraft.util.Identifier;

/** Custom screen typography; gameplay HUD and resource-pack defaults remain independent. */
final class ClientUiFont {
    private static final Style STYLE = Style.EMPTY.withFont(Identifier.tryParse("cubeon-client:ui"));
    private ClientUiFont() { }
    static Text text(String value) { return Text.literal(value).setStyle(STYLE); }
}
