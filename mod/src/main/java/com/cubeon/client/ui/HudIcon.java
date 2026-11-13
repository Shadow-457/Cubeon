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
        {"10101","11111","01110","01110","11111"}, // cosmetics
        {"10000","11000","11100","11000","10000"}, // menu motion
        {"11111","10101","11111","00100","01110"}, // own name tag
        {"11100","01110","00111","01110","11100"} // motion blur+
    };
    private static final String[][] TOOLS={
        { // HUD layout: window, widgets and a bottom-right resize grip
            "111111111","100000001","101101001","101101001","100000001",
            "101011101","101011101","100000111","111111111"
        },
        { // themes: a small palette with three paint wells
            "001111100","011111110","110101011","111111111","111111111",
            "111111110","011110000","001111100","000111000"
        },
        { // cosmetics: Minecraft-style chest piece
            "110000011","111000111","011111110","011111110","001111100",
            "001111100","001111100","001111100","001111100"
        },
        { // reset: circular arrow
            "001111000","011001100","110000000","110011100","110001100",
            "110001100","011001100","001111000","000110000"
        },
        { // emotes: friendly face
            "001111100","011111110","110000011","110101011","110000011",
            "110101011","110010011","011111110","001111100"
        },
        { // friends/chat: two people and a speech tail
            "011001100","111111110","111111110","011001100","000000000",
            "111111111","111111111","011111110","001001100"
        },
        { // done
            "110000011","011000110","001101100","000111000","000111000",
            "001101100","011000110","110000011","000000000"
        }
    };
    private HudIcon() { }
    public static void gear(ClientUi.Canvas c,int x,int y,float fade) {
        int color=ClientUi.alpha(MenuUi.DIM,fade);
        c.fill(x+2,y+2,x+8,y+8,color);
        c.fill(x+4,y,x+6,y+10,color);
        c.fill(x,y+4,x+10,y+6,color);
        c.fill(x+4,y+4,x+6,y+6,ClientUi.alpha(MenuUi.SURFACE_HI,fade));
    }
    public static void settings(ClientUi.Canvas c,int x,int y,int size,float hover,float fade) {
        int fill=ClientUi.mix(MenuUi.SURFACE,MenuUi.SELECTED,hover);
        int border=ClientUi.mix(MenuUi.BORDER,MenuUi.BORDER_HI,hover);
        MenuUi.panel(c,x,y,size,size,4,fill,border,fade);
        int color=ClientUi.alpha(ClientUi.mix(MenuUi.DIM,MenuUi.ACCENT_HI,.15f+.85f*hover),fade);
        int pad=Math.max(2,size/6);
        if(c.textures()) c.image("textures/ui/tools.png",x+pad,y+pad,size-pad*2,size-pad*2,
                0,0,128,128,896,128,color);
        else gear(c,x+(size-10)/2,y+(size-10)/2,fade);
    }
    public static void draw(ClientUi.Canvas c,int index,int x,int y,int size,float fade) {
        draw(c,index,x,y,size,true,fade);
    }
    public static void draw(ClientUi.Canvas c,int index,int x,int y,int size,boolean active,float fade) {
        ClientUi.rounded(c,x,y,size,size,4,ClientUi.alpha(active?MenuUi.SELECTED:MenuUi.SURFACE,fade));
        String[] rows=ART[index%ART.length]; int unit=2,left=x+(size-10)/2,top=y+(size-10)/2;
        for(int row=0;row<5;row++) for(int col=0;col<5;col++) if(rows[row].charAt(col)=='1')
            c.fill(left+col*unit,top+row*unit,left+(col+1)*unit,top+(row+1)*unit,
                    ClientUi.alpha(active?MenuUi.ACCENT_HI:MenuUi.FAINT,fade));
    }
    public static void tool(ClientUi.Canvas c,int action,int x,int y,int size,float hover,float fade) {
        int art=switch(action) {
            case HudMenu.HUD_EDITOR->0; case HudMenu.THEMES->1; case HudMenu.SKINS->2;
            case HudMenu.RESET->3; case HudMenu.EMOTES->4; case HudMenu.FRIENDS->5;
            case HudMenu.DONE->6; default->-1;
        };
        if(art<0) return;
        int fill=ClientUi.mix(MenuUi.SURFACE_HI,MenuUi.SELECTED,hover);
        int border=ClientUi.mix(MenuUi.BORDER,MenuUi.BORDER_HI,hover);
        MenuUi.panel(c,x,y,size,size,5,fill,border,fade);
        int color=ClientUi.alpha(ClientUi.mix(MenuUi.DIM,MenuUi.ACCENT_HI,.15f+.85f*hover),fade);
        if(c.textures()) {
            int pad=Math.max(2,size/7);
            c.image("textures/ui/tools.png",x+pad,y+pad,size-pad*2,size-pad*2,
                    art*128,0,128,128,896,128,color);
            return;
        }
        String[] rows=TOOLS[art]; int unit=Math.max(1,(size-8)/9),pixels=unit*9;
        int left=x+(size-pixels)/2,top=y+(size-pixels)/2;
        for(int row=0;row<9;row++) for(int col=0;col<9;col++) if(rows[row].charAt(col)=='1')
            c.fill(left+col*unit,top+row*unit,left+(col+1)*unit,top+(row+1)*unit,color);
    }
}
