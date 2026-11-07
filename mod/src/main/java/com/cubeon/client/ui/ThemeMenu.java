package com.cubeon.client.ui;

/** Palette presets and an explicit, validated custom editor inside the K menu. */
public final class ThemeMenu {
    public static final int PRESET=110, ROLE=116, FIELD=122, APPLY=123;
    private int index=ClientTheme.selected(), role;
    private int[] draft=ClientTheme.colors();
    private String hex=ClientTheme.hex(draft[0]), error="";
    private boolean focused, replace;
    public boolean focused() { return focused; }
    public boolean back() { if(focused) { focused=false; return true; } return false; }
    public boolean type(int cp) {
        if(!focused) return false;
        if(Character.digit(cp,16)>=0 && cp<128) {
            if(replace) { hex=""; replace=false; }
            if(hex.length()<6) hex+=(char)cp;
            if(ClientTheme.validHex(hex)) draft[role]=Integer.parseInt(hex,16);
            error="";
        }
        return true;
    }
    public boolean backspace() {
        if(!focused) return false;
        if(replace) { hex=""; replace=false; }
        else if(!hex.isEmpty()) hex=hex.substring(0,hex.length()-1);
        return true;
    }
    private boolean valid() {
        if(index==5 && !ClientTheme.validHex(hex)) { error="Enter all six hex digits"; return false; }
        return true;
    }
    public void activate(int action) {
        if(action>=PRESET && action<PRESET+6) {
            if(!valid()) return;
            index=action-PRESET; draft=ClientTheme.preset(index); hex=ClientTheme.hex(draft[role]); focused=false; error="";
        } else if(action>=ROLE && action<ROLE+6 && index==5) {
            if(!valid()) return;
            role=action-ROLE; hex=ClientTheme.hex(draft[role]); focused=true; replace=true;
        } else if(action==FIELD && index==5) { focused=true; replace=true; }
        else if(action==APPLY && valid()) {
            if(ClientTheme.apply(index,draft)) { focused=false; error="Saved"; MenuUi.refreshTheme(); }
            else error="Could not save theme. Try again.";
        } else focused=false;
    }
    public void layout(HudMenu.Rect[] controls,int x,int y,int w,int h) {
        int cell=(w-36)/3;
        for(int i=0;i<6;i++) controls[PRESET+i]=new HudMenu.Rect(x+12+(i%3)*(cell+6),y+36+(i/3)*28,cell,24);
        if(index==5) {
            for(int i=0;i<6;i++) controls[ROLE+i]=new HudMenu.Rect(x+12+(i%3)*(cell+6),y+96+(i/3)*21,cell,18);
            controls[FIELD]=new HudMenu.Rect(x+12,y+142,(w-30)/2,22);
        }
        controls[HudMenu.BACK]=new HudMenu.Rect(x+12,y+h-34,76,24);
        controls[APPLY]=new HudMenu.Rect(x+w-88,y+h-34,76,24);
    }
    public void render(ClientUi.Canvas c,HudMenu.Rect[] controls,int x,int y,int w,int h,int selection) {
        MenuUi.palette(draft);
        try {
            MenuUi.panel(c,x,y,w,h,6,MenuUi.SURFACE,MenuUi.BORDER_HI,1);
            MenuUi.mark(c,x+12,y+9,1);
            ClientUi.left(c,c.translate("cubeonclient.menu.themes"),x+40,y+14,MenuUi.TEXT);
            for(int i=0;i<6;i++) {
                var r=controls[PRESET+i];
                MenuUi.panel(c,r.x(),r.y(),r.w(),r.h(),5,i==index?MenuUi.SELECTED:MenuUi.SURFACE_HI,
                        selection==PRESET+i || i==index?MenuUi.ACCENT:MenuUi.BORDER,1);
                c.fill(r.x()+7,r.y()+8,r.x()+15,r.y()+16,0xFF000000|ClientTheme.preset(i)[0]);
                ClientUi.left(c,ClientUi.fit(c,ClientTheme.NAMES[i],r.w()-27),r.x()+21,r.y()+8,MenuUi.TEXT);
            }
            if(index==5) {
                for(int i=0;i<6;i++) {
                    var r=controls[ROLE+i];
                    MenuUi.panel(c,r.x(),r.y(),r.w(),r.h(),4,MenuUi.SURFACE_HI,i==role?MenuUi.ACCENT:MenuUi.BORDER,1);
                    c.fill(r.x()+5,r.y()+5,r.x()+13,r.y()+13,0xFF000000|draft[i]);
                    ClientUi.left(c,ClientUi.fit(c,ClientTheme.ROLES[i],r.w()-22),r.x()+18,r.y()+5,MenuUi.TEXT);
                }
                var r=controls[FIELD];
                MenuUi.panel(c,r.x(),r.y(),r.w(),r.h(),5,MenuUi.SURFACE_HI,focused?MenuUi.ACCENT:MenuUi.BORDER,1);
                ClientUi.left(c,"#"+hex.toUpperCase(java.util.Locale.ROOT)+(focused?" |":""),r.x()+8,r.y()+7,MenuUi.TEXT);
                MenuUi.button(c,r.x()+r.w()+6,r.y(),r.w(),r.h(),"Preview",0,true,1);
                ClientUi.left(c,ClientUi.fit(c,error.isEmpty()?"Select a color; type its hex code":error,w-24),x+12,y+170,MenuUi.DIM);
            } else {
                MenuUi.panel(c,x+12,y+100,w-24,64,6,MenuUi.SURFACE_HI,MenuUi.BORDER,1);
                c.text(ClientTheme.NAMES[index]+" theme",x+w/2,y+112,MenuUi.TEXT);
                MenuUi.button(c,x+w/2-48,y+132,96,22,"Preview",0,true,1);
                ClientUi.left(c,ClientUi.fit(c,error.isEmpty()?"Apply to save this menu theme":error,w-24),x+12,y+170,MenuUi.DIM);
            }
            var back=controls[HudMenu.BACK]; var apply=controls[APPLY];
            MenuUi.button(c,back.x(),back.y(),back.w(),back.h(),"Back",selection==HudMenu.BACK?1:0,false,1);
            MenuUi.button(c,apply.x(),apply.y(),apply.w(),apply.h(),"Apply",selection==APPLY?1:0,true,1);
        } finally { MenuUi.refreshTheme(); }
    }
}
