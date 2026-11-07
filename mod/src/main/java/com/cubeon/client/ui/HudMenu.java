package com.cubeon.client.ui;

import com.cubeon.client.hud.HudFeatures;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.Locale;

/** Searchable feature catalogue shared by all native Minecraft adapters. */
public final class HudMenu {
    // Existing action IDs are retained for the original five overlays and tools.
    public static final int EMOTES=15, HEALTH=16, ANIMATIONS=17, WING_DEPTH=18,
            OTHER_COSMETICS=19, CAMERA_BLUR=20, BLUR_INTENSITY=21, RESET=22,
            FRIENDS=23, DONE=24, SPRINT=53, CLOCK_MODE=54, SKINS=55, MENU_ANIMATIONS=56, OWN_NAME_TAG=57, BLUR_PLUS=58, BLUR_PLUS_STRENGTH=59,
            DETAIL=70, SEARCH=100, CATEGORY=101, PREVIOUS=107, NEXT=108, BACK=109,
            THEMES=60, ACTION_COUNT=124, NONE=-1;
    private static final String[] CATEGORIES={"All", "HUD", "Player", "Render", "Movement", "Cosmetics"};
    private static final HudFeatures[] OVERLAYS=HudFeatures.values();
    public interface Settings {
        boolean visible(int overlay); float scale(int overlay);
        boolean health(); boolean animations(); boolean wingDepth(); boolean otherCosmetics();
        boolean cameraBlur(); float blurIntensity();
        default boolean sprint() { return false; }
        default boolean worldClock() { return false; }
        default boolean blurPlus() { return false; }
        default float blurPlusStrength() { return 1; }
        default void setBlurPlusStrength(float value) { }
        default boolean ownNameTag() { return false; }
        default boolean menuAnimations() { return true; }
        default void setScale(int overlay, float value) { }
        default void save() { }
    }
    public record Rect(int x,int y,int w,int h) {
        public boolean contains(double px,double py) { return px>=x&&px<x+w&&py>=y&&py<y+h; }
    }
    private record Feature(String slot,String category,int action,int overlay) { }
    private static final Feature[] FEATURES;
    static {
        var features=new ArrayList<Feature>();
        for (HudFeatures feature:OVERLAYS) features.add(new Feature(feature.slot,feature.category,toggleAction(feature.ordinal()),feature.ordinal()));
        features.add(new Feature("sprint","Movement",SPRINT,-1));
        features.add(new Feature("camera_blur","Render",CAMERA_BLUR,-1));
        features.add(new Feature("health","Player",HEALTH,-1));
        features.add(new Feature("animations","Cosmetics",ANIMATIONS,-1));
        features.add(new Feature("wing_depth","Cosmetics",WING_DEPTH,-1));
        features.add(new Feature("other_cosmetics","Cosmetics",OTHER_COSMETICS,-1));
        features.add(new Feature("menu_animations","Render",MENU_ANIMATIONS,-1));
        features.add(new Feature("own_name_tag","Player",OWN_NAME_TAG,-1));
        features.add(new Feature("motion_blur_plus","Render",BLUR_PLUS,-1));
        FEATURES=features.toArray(Feature[]::new);
    }
    public static int toggleAction(int overlay) { return overlay<5?overlay*3:25+(overlay-5)*3; }
    public static int overlayIndex(int action) { return action>=0&&action<15?action/3:action>=25&&action<25+(OVERLAYS.length-5)*3?5+(action-25)/3:-1; }
    public static int overlayOperation(int action) { return action<15?action%3:(action-25)%3; }
    public static int featureCount() { return FEATURES.length; }
    private final Rect[] controls=new Rect[ACTION_COUNT], cards=new Rect[FEATURES.length];
    private final float[] glow=new float[ACTION_COUNT];
    private final float[] toggleMotion=new float[FEATURES.length];
    private boolean initializedToggles;
    private int draggingScale=-1, drawOffset;
    private boolean scaleChanged;
    private int width,height,x,y,panelWidth,panelHeight,selection=NONE,category,page,pages=1,detail=-1;
    private boolean searchFocused,ignoreNextSlash,dirty=true,compact;
    private String query="";
    private int[] filtered=new int[0];
    private double lastX=Double.NaN,lastY=Double.NaN;
    private final long opened=System.nanoTime();
    private long lastFrame=opened;
    private long changedAt=opened;
    private Settings latest;
    private ThemeMenu themes;
    public Rect control(int action) { return action>=0&&action<ACTION_COUNT?controls[action]:null; }
    public Rect inputControl() { return controls[themes==null?SEARCH:ThemeMenu.FIELD]; }
    public int selection() { return selection; }
    public String query() { return query; }
    public boolean searchFocused() { return themes==null?searchFocused:themes.focused(); }
    public int pages() { return pages; }
    public int page() { return page; }
    public boolean back() {
        if(themes!=null) { if(!themes.back()) { themes=null; dirty=true; } return true; }
        if(searchFocused) { searchFocused=false; return true; }
        if(detail>=0) { finishScale(); detail=-1; dirty=true; changedAt=System.nanoTime(); return true; }
        return false;
    }
    public void focusSearch() { if(themes!=null) return; detail=-1; searchFocused=true; dirty=true; }
    public void focusSearchShortcut() { focusSearch(); ignoreNextSlash=true; }
    public boolean type(int codepoint) {
        if(themes!=null) return themes.type(codepoint);
        if(!searchFocused) return false;
        if(ignoreNextSlash) { ignoreNextSlash=false; if(codepoint=='/') return true; }
        if(!Character.isISOControl(codepoint)&&Character.isValidCodePoint(codepoint)&&query.codePointCount(0,query.length())<40) {
            query+=new String(Character.toChars(codepoint)); page=0; dirty=true;
        }
        return true;
    }
    public boolean backspace() {
        if(themes!=null) return themes.backspace();
        if(!searchFocused) return false;
        if(!query.isEmpty()) query=query.substring(0,query.offsetByCodePoints(query.length(),-1));
        page=0; dirty=true; return true;
    }
    public boolean activate(int action) {
        if(themes!=null) {
            if(action==BACK) { themes=null; dirty=true; }
            else { themes.activate(action); dirty=true; }
            return true;
        }
        if(action==THEMES) { finishScale(); themes=new ThemeMenu(); searchFocused=false; dirty=true; return true; }
        if(action==SEARCH) { focusSearch(); return true; }
        searchFocused=false;
        if(action>=CATEGORY&&action<CATEGORY+CATEGORIES.length) { finishScale(); category=action-CATEGORY; page=0; detail=-1; dirty=true; changedAt=System.nanoTime(); return true; }
        if(action==PREVIOUS||action==NEXT) { scroll(action==NEXT?1:-1); return true; }
        if(action==BACK) { finishScale(); detail=-1; dirty=true; changedAt=System.nanoTime(); return true; }
        if(action>=DETAIL&&action<DETAIL+FEATURES.length) { finishScale(); detail=action-DETAIL; dirty=true; changedAt=System.nanoTime(); return true; }
        return false;
    }
    public boolean scroll(int amount) {
        if(themes!=null) return true;
        if(detail>=0) return false;
        int next=Math.max(0,Math.min(pages-1,page+amount));
        if(next!=page) changedAt=System.nanoTime();
        page=next; dirty=true; return true;
    }
    public int hit(double px,double py) {
        py-=drawOffset;
        for(int i=0;i<controls.length;i++) if(controls[i]!=null&&controls[i].contains(px,py)) return i;
        return NONE;
    }
    private int scaleOverlay(int action) {
        int index=overlayIndex(action);
        return detail>=0&&index>=0&&overlayOperation(action)==2&&controls[action]!=null?index:-1;
    }
    public boolean beginScale(double px,double py) {
        if(themes!=null) return false;
        int action=hit(px,py), index=scaleOverlay(action);
        if(latest==null) return false;
        if(action==BLUR_PLUS_STRENGTH) index=-2;
        else if(index<0) return false;
        searchFocused=false; selection=action; draggingScale=index; scaleChanged=false;
        return dragScale(px);
    }
    public boolean dragScale(double px) {
        if(draggingScale==-1||latest==null) return false;
        Rect r=controls[draggingScale==-2?BLUR_PLUS_STRENGTH:toggleAction(draggingScale)+2];
        if(r==null) { finishScale(); return false; }
        float fraction=(float)Math.max(0,Math.min(1,(px-r.x-10)/Math.max(1,r.w-20)));
        float value=Math.round(((draggingScale==-2?.25f:.5f)+fraction*(draggingScale==-2?1.75f:1.5f))*100)/100f;
        setScale(draggingScale,value);
        return true;
    }
    private void setScale(int overlay,float value) {
        if(Math.abs((overlay==-2?latest.blurPlusStrength():latest.scale(overlay))-value)>.0001f) {
            if(overlay==-2) latest.setBlurPlusStrength(value); else latest.setScale(overlay,value); scaleChanged=true;
        }
    }
    public boolean finishScale() {
        if(draggingScale==-1) return false;
        draggingScale=-1;
        if(scaleChanged&&latest!=null) latest.save();
        scaleChanged=false; return true;
    }
    public boolean adjustScale(float amount) {
        int index=selection==BLUR_PLUS_STRENGTH?-2:scaleOverlay(selection);
        if(index==-1||latest==null) return false;
        float current=index==-2?latest.blurPlusStrength():latest.scale(index);
        float value=Math.max(index==-2?.25f:.5f,Math.min(2,Math.round((current+amount)*100)/100f));
        setScale(index,value);
        if(scaleChanged) latest.save();
        scaleChanged=false; return true;
    }
    public void step(int direction) {
        searchFocused=false;
        int next=selection;
        for(int i=0;i<ACTION_COUNT;i++) { next=Math.floorMod(next+direction,ACTION_COUNT); if(controls[next]!=null) { selection=next; return; } }
    }
    public void layout(int w,int h) {
        if(!dirty&&w==width&&h==height) return;
        width=w; height=h; dirty=false;
        Arrays.fill(controls,null); Arrays.fill(cards,null);
        panelWidth=Math.min(w-32,Math.min(560,Math.max(288,Math.round(w*.80f))));
        panelHeight=Math.min(h-24,Math.min(320,Math.max(216,Math.round(h*.78f))));
        x=(w-panelWidth)/2; y=(h-panelHeight)/2; compact=panelWidth<496||panelHeight<290;
        if(themes!=null) { themes.layout(controls,x,y,panelWidth,panelHeight); return; }
        controls[THEMES]=new Rect(x+panelWidth-84,y+9,72,20);
        int footer=y+panelHeight-34, footerW=(panelWidth-48)/5;
        int[] footerIds={SKINS,RESET,EMOTES,FRIENDS,DONE};
        for(int i=0;i<5;i++) controls[footerIds[i]]=new Rect(x+12+i*(footerW+6),footer,footerW,24);
        if(detail>=0) {
            controls[BACK]=new Rect(x+12,y+40,72,22);
            Feature f=FEATURES[detail]; int top=y+100, row=28, cell=(panelWidth-30)/2;
            controls[f.action]=new Rect(x+12,top,cell,24);
            if(f.overlay>=0) {
                controls[f.action+1]=new Rect(x+18+cell,top,cell,24);
                controls[f.action+2]=new Rect(x+12,top+row,cell,36);
            }
            if(f.action==BLUR_PLUS) controls[BLUR_PLUS_STRENGTH]=new Rect(x+12,top+row,cell,36);
            if(f.slot.equals("clock")) controls[CLOCK_MODE]=new Rect(x+18+cell,top+row,cell,24);
            if(f.slot.equals("camera_blur")) controls[BLUR_INTENSITY]=new Rect(x+18+cell,top,cell,24);
        } else {
            controls[SEARCH]=new Rect(x+12,y+36,panelWidth-24,22);
            int categoryTop=y+64;
            for(int i=0;i<CATEGORIES.length;i++) {
                int cw=(panelWidth-24-5*4)/6;
                controls[CATEGORY+i]=new Rect(x+12+i*(cw+4),categoryTop,cw,20);
            }
            int left=x+12, top=y+90, availableW=panelWidth-24;
            int cols=availableW>=480?3:2;
            int room=footer-top-34;
            int rows=room>=108?2:1, capacity=cols*rows;
            var matches=new ArrayList<Integer>(); String needle=query.toLowerCase(Locale.ROOT).trim();
            for(int i=0;i<FEATURES.length;i++) {
                Feature f=FEATURES[i];
                String label=latest==null?f.slot:latestLabel(f);
                if((category==0||f.category.equals(CATEGORIES[category]))&&(needle.isEmpty()||(label+" "+f.slot+" "+f.category).toLowerCase(Locale.ROOT).contains(needle))) matches.add(i);
            }
            filtered=matches.stream().mapToInt(Integer::intValue).toArray();
            pages=Math.max(1,(filtered.length+capacity-1)/capacity); page=Math.min(page,pages-1);
            int cw=(availableW-(cols-1)*8)/cols;
            int cardHeight=Math.min(68,(room-(rows-1)*8)/rows);
            for(int j=0;j<capacity&&page*capacity+j<filtered.length;j++) {
                int index=filtered[page*capacity+j]; Feature f=FEATURES[index];
                int cx=left+(j%cols)*(cw+8),cy=top+(j/cols)*(cardHeight+8);
                cards[index]=new Rect(cx,cy,cw,cardHeight);
                controls[f.action]=new Rect(cx+cw-36,cy+6,28,20);
                controls[DETAIL+index]=new Rect(cx+6,cy+cardHeight-19,cw-12,18);
            }
            controls[PREVIOUS]=new Rect(left,footer-28,28,20);
            controls[NEXT]=new Rect(left+availableW-28,footer-28,28,20);
        }
        if(selection>=0&&controls[selection]==null) selection=NONE;
    }
    private final String[] featureLabels=new String[FEATURES.length];
    private String latestLabel(Feature f) { for(int i=0;i<FEATURES.length;i++) if(FEATURES[i]==f) return featureLabels[i]==null?f.slot:featureLabels[i]; return f.slot; }
    private boolean enabled(Feature f,Settings s) {
        if(f.overlay>=0) return s.visible(f.overlay);
        return switch(f.action) { case SPRINT->s.sprint(); case HEALTH->s.health();
            case ANIMATIONS->s.animations(); case WING_DEPTH->s.wingDepth(); case OTHER_COSMETICS->s.otherCosmetics();
            case CAMERA_BLUR->s.cameraBlur(); case MENU_ANIMATIONS->s.menuAnimations(); case OWN_NAME_TAG->s.ownNameTag(); case BLUR_PLUS->s.blurPlus(); default->false; };
    }
    public void render(ClientUi.Canvas canvas,int w,int h,int mx,int my,Settings s) {
        if(featureLabels[0]==null) { for(int i=0;i<FEATURES.length;i++) featureLabels[i]=canvas.translate("cubeonclient.hud."+FEATURES[i].slot); dirty=true; } latest=s; layout(w,h);
        if(themes!=null) {
            drawOffset=0;
            if(lastX!=mx || lastY!=my) { selection=hit(mx,my); lastX=mx; lastY=my; }
            themes.render(canvas,controls,x,y,panelWidth,panelHeight,selection); return;
        }
        long now=System.nanoTime();
        float ease=s.menuAnimations()?1-(float)Math.exp(-Math.min(.1f,(now-lastFrame)/1e9f)*18):1; lastFrame=now;
        float opening=s.menuAnimations()?progress(now,opened,220_000_000f):1;
        drawOffset=Math.round((1-opening)*8);
        if(draggingScale==-1&&(lastX!=mx||lastY!=my)) { selection=hit(mx,my); lastX=mx; lastY=my; }
        canvas=MenuUi.transform(canvas,drawOffset,opening);
        float fade=1;
        for(int i=0;i<glow.length;i++) glow[i]+=((selection==i?1:0)-glow[i])*ease;
        for(int i=0;i<FEATURES.length;i++) {
            float target=enabled(FEATURES[i],s)?1:0;
            toggleMotion[i]=initializedToggles?toggleMotion[i]+(target-toggleMotion[i])*ease:target;
        }
        initializedToggles=true;
        MenuUi.panel(canvas,x,y,panelWidth,panelHeight,10,MenuUi.SURFACE,MenuUi.BORDER_HI,fade);
        MenuUi.mark(canvas,x+12,y+9,fade);
        ClientUi.left(canvas,canvas.translate("cubeonclient.menu.title"),x+40,y+14,ClientUi.alpha(MenuUi.TEXT,fade));
        ClientUi.Canvas frame=canvas;
        if(s.menuAnimations()) canvas=MenuUi.transform(canvas,0,.55f+.45f*progress(now,changedAt,130_000_000f));
        if(detail>=0) {
            Feature f=FEATURES[detail];
            action(canvas,BACK,canvas.translate("cubeonclient.menu.back"),false,fade);
            ClientUi.left(canvas,latestLabel(f),x+94,y+47,ClientUi.alpha(MenuUi.TEXT,fade));
            String hint=canvas.translate("cubeonclient.hud."+f.slot+"_hint");
            ClientUi.left(canvas,ClientUi.fit(canvas,hint,panelWidth-24),x+12,y+77,ClientUi.alpha(MenuUi.DIM,fade));
            action(canvas,f.action,canvas.translate(enabled(f,s)?"cubeonclient.menu.enabled":"cubeonclient.menu.disabled"),enabled(f,s),fade);
            if(f.overlay>=0) {
                action(canvas,f.action+1,canvas.translate("cubeonclient.menu.move"),false,fade);
                slider(canvas,f.action+2,s.scale(f.overlay),fade);
            }
            if(f.action==BLUR_PLUS) slider(canvas,BLUR_PLUS_STRENGTH,s.blurPlusStrength(),fade);
            action(canvas,CLOCK_MODE,canvas.translate(s.worldClock()?"cubeonclient.menu.world_time":"cubeonclient.menu.system_time"),false,fade);
            action(canvas,BLUR_INTENSITY,canvas.translate("cubeonclient.hud.blur_intensity")+": "+Math.round(s.blurIntensity()*100)+"%",false,fade);
        } else {
            Rect search=controls[SEARCH];
            MenuUi.panel(canvas,search.x,search.y,search.w,search.h,6,MenuUi.SURFACE_HI,searchFocused?MenuUi.ACCENT:MenuUi.BORDER,fade);
            String text=query.isEmpty()?canvas.translate("cubeonclient.menu.search"):query;
            ClientUi.left(canvas,ClientUi.fit(canvas,text+(searchFocused?" |":""),search.w-16),search.x+8,search.y+8,ClientUi.alpha(query.isEmpty()?MenuUi.FAINT:MenuUi.TEXT,fade));
            for(int i=0;i<CATEGORIES.length;i++) {
                Rect r=controls[CATEGORY+i];
                MenuUi.panel(canvas,r.x,r.y,r.w,r.h,5,category==i?MenuUi.SELECTED:MenuUi.SURFACE,
                        category==i?MenuUi.BORDER_HI:ClientUi.mix(MenuUi.SURFACE,MenuUi.BORDER,glow[CATEGORY+i]),fade);
                canvas.text(ClientUi.fit(canvas,canvas.translate("cubeonclient.menu.category_"+CATEGORIES[i].toLowerCase(Locale.ROOT)),r.w-8),r.x+r.w/2,r.y+6,
                        ClientUi.alpha(category==i?MenuUi.ACCENT_HI:MenuUi.DIM,fade));
            }
            for(int i=0;i<FEATURES.length;i++) {
                Rect card=cards[i]; if(card==null) continue; Feature f=FEATURES[i];
                float hover=Math.max(glow[f.action],glow[DETAIL+i]);
                MenuUi.panel(canvas,card.x,card.y,card.w,card.h,6,MenuUi.SURFACE_HI,ClientUi.mix(MenuUi.BORDER,MenuUi.ACCENT,hover),fade);
                HudIcon.draw(canvas,i,card.x+8,card.y+5,card.h<60?14:20,fade);
                Rect toggle=controls[f.action];
                MenuUi.toggle(canvas,toggle.x+2,toggle.y+4,toggleMotion[i],fade);
                if(glow[f.action]>.1f) MenuUi.panel(canvas,toggle.x,toggle.y,toggle.w,toggle.h,6,0x00000000,ClientUi.alpha(MenuUi.ACCENT,glow[f.action]),fade);
                ClientUi.left(canvas,ClientUi.fit(canvas,latestLabel(f),card.w-16),card.x+8,card.y+(card.h<60?23:31),ClientUi.alpha(MenuUi.TEXT,fade));
                Rect gear=controls[DETAIL+i];
                ClientUi.left(canvas,ClientUi.fit(canvas,canvas.translate("cubeonclient.menu.configure"),gear.w-26),gear.x+2,gear.y+3,ClientUi.alpha(ClientUi.mix(MenuUi.FAINT,MenuUi.TEXT,glow[DETAIL+i]),fade));
                HudIcon.gear(canvas,gear.x+gear.w-14,gear.y+3,fade);
            }
            if(filtered.length==0) canvas.text(canvas.translate("cubeonclient.menu.no_matches"),x+panelWidth/2,y+panelHeight/2,ClientUi.alpha(MenuUi.DIM,fade));
            action(canvas,PREVIOUS,"‹",false,fade); action(canvas,NEXT,"›",false,fade);
            canvas.text((page+1)+" / "+pages,x+panelWidth/2,y+panelHeight-54,ClientUi.alpha(MenuUi.FAINT,fade));
        }
        canvas=frame;
        action(canvas,THEMES,canvas.translate("cubeonclient.menu.themes"),false,fade);
        action(canvas,RESET,canvas.translate("cubeonclient.hud.reset"),false,fade);
        action(canvas,SKINS,canvas.translate("cubeonclient.cosmetics.title"),false,fade);
        action(canvas,EMOTES,canvas.translate("cubeonclient.hud.emotes"),false,fade);
        action(canvas,FRIENDS,canvas.translate("cubeonclient.friends.title"),false,fade);
        action(canvas,DONE,canvas.translate("cubeonclient.emotes.done"),true,fade);
    }
    private static float progress(long now,long start,float duration) {
        float t=Math.max(0,Math.min(1,(now-start)/duration));
        return 1-(1-t)*(1-t)*(1-t);
    }
    private void slider(ClientUi.Canvas canvas,int action,float value,float fade) {
        Rect r=controls[action]; if(r==null) return;
        MenuUi.panel(canvas,r.x,r.y,r.w,r.h,6,MenuUi.SURFACE_HI,
                selection==action?MenuUi.BORDER_HI:MenuUi.BORDER,fade);
        ClientUi.left(canvas,canvas.translate(action==BLUR_PLUS_STRENGTH?"cubeonclient.hud.motion_blur_plus_strength":"cubeonclient.menu.size")+"  "+(action==BLUR_PLUS_STRENGTH?Math.round(value*100)+"%":String.format(Locale.ROOT,"%.2f×",value)),
                r.x+10,r.y+3,ClientUi.alpha(MenuUi.TEXT,fade));
        int left=r.x+10,track=r.w-20,cy=r.y+25;
        float fraction=Math.max(0,Math.min(1,(value-(action==BLUR_PLUS_STRENGTH?.25f:.5f))/(action==BLUR_PLUS_STRENGTH?1.75f:1.5f)));
        ClientUi.rounded(canvas,left,cy-2,track,4,2,ClientUi.alpha(MenuUi.BORDER,fade));
        ClientUi.rounded(canvas,left,cy-2,Math.round(track*fraction),4,2,ClientUi.alpha(MenuUi.ACCENT,fade));
        ClientUi.rounded(canvas,left+Math.round(track*fraction)-5,cy-5,10,10,5,
                ClientUi.alpha(selection==action?MenuUi.TEXT:MenuUi.DIM,fade));
    }
    public static float nextBlurIntensity(float value) {
        int step=Float.isFinite(value)?Math.round(value*4):4;
        return (Math.floorMod(Math.max(1,Math.min(8,step)),8)+1)/4f;
    }
    private void action(ClientUi.Canvas canvas,int id,String text,boolean primary,float fade) {
        Rect r=controls[id]; if(r!=null) MenuUi.button(canvas,r.x,r.y,r.w,r.h,text,glow[id],primary,fade);
    }
}
