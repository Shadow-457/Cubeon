package com.cubeon.client.ui;

/** Small, consistent pixel artwork drawn with a bounded set of native quads. */
public final class HudIcon {
    private static final String[][] ART={
        {"11111","10000","11110","10000","10000"}, // FPS
        {"00100","01110","10101","11111","00000"}, // keys
        {"11011","11111","01110","01110","01110"}, // armor
        {"00001","00101","10101","10101","10101"}, // ping
        {"01110","01010","11011","10001","11111"}, // clicks
        {"01110","10101","10111","10001","01110"}, // clock
        {"11111","10001","10101","10001","11111"}, // system
        {"01110","00100","01110","11011","11111"}, // potion
        {"00100","10101","01110","10101","00100"}, // coordinates
        {"00100","01110","11111","00100","00100"}, // compass
        {"00100","01110","11111","00100","00100"}, // biome
        {"10101","01110","11111","01110","10101"}, // light
        {"10100","10101","01110","00100","00100"}, // combo
        {"00011","00110","01100","11110","10011"}, // sprint
        {"11000","11110","11111","01111","00011"}, // blur
        {"01010","11111","11111","01110","00100"}, // health
        {"00100","10101","01110","10101","00100"}, // animation
        {"10001","11011","11111","01110","00100"}, // wings
        {"10101","11111","01110","01110","11111"} // cosmetics
    };
    private HudIcon() { }
    public static void gear(ClientUi.Canvas c,int x,int y,float fade) {
        int color=ClientUi.alpha(ClientUi.DIM,fade);
        c.fill(x+2,y+2,x+8,y+8,color);
        c.fill(x+4,y,x+6,y+10,color);
        c.fill(x,y+4,x+10,y+6,color);
        c.fill(x+4,y+4,x+6,y+6,ClientUi.alpha(ClientUi.SURFACE_HI,fade));
    }
    public static void draw(ClientUi.Canvas c,int index,int x,int y,int size,float fade) {
        ClientUi.rounded(c,x,y,size,size,4,ClientUi.alpha(ClientUi.SELECTED,fade));
        String[] rows=ART[index%ART.length]; int unit=2,left=x+(size-10)/2,top=y+(size-10)/2;
        for(int row=0;row<5;row++) for(int col=0;col<5;col++) if(rows[row].charAt(col)=='1')
            c.fill(left+col*unit,top+row*unit,left+(col+1)*unit,top+(row+1)*unit,ClientUi.alpha(ClientUi.ACCENT_HI,fade));
    }
}
