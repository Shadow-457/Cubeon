package com.cubeon.client.ui;

import com.cubeon.client.skins.SkinLibrary;
import com.cubeon.client.skins.SkinPreview;
import com.cubeon.client.skins.LiveCape;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;

/** Full-screen Minecraft wardrobe. Selecting/rotating never applies the skin. */
public final class SkinMenu implements AutoCloseable {
    public static final int SEARCH=0,LOOKUP=1,IMPORT=2,APPLY=3,MODEL=4,LEFT=5,RIGHT=6,BACK=7,
            PREVIOUS=8,NEXT=9,REFRESH=10,DELETE=11,GRID=12,EXPORT=13,RESET=14,
            SKINS=15,CAPES=16,CAPE_VISIBLE=17,CAPE_IMPORT=18,ROW=20,LAYER=40;
    public interface Layers {
        int mask();
        void set(int mask);
    }
    private static final int WHITE=0xFFFFFFFF,DIM=0xFFAAAAAA,GREY=0xB839393B,RIM=0xFF727275;
    private static final String[] PARTS={"hat","jacket","right_sleeve","left_sleeve","right_pants","left_pants"};
    private final SkinLibrary library=new SkinLibrary();
    private final SkinLibrary capeLibrary=new SkinLibrary("cape");
    private final SkinPreview preview=new SkinPreview();
    private final Layers layers;
    private final HudMenu.Rect[] controls=new HudMenu.Rect[46];
    private String username="",deleteId="";
    private boolean focused,dragging,grid,capes,capeOpened;
    private long seenCapeRevision=LiveCape.get()==null?0:LiveCape.get().revision();
    private int selection=-1,yaw=-20,firstRow;
    private HudMenu.Rect modelRect;
    private double lastX=Double.NaN,lastY=Double.NaN,dragX;
    public SkinMenu() { this(new Layers() {
        private int mask=127;
        public int mask() { return mask; }
        public void set(int value) { mask=value; }
    }); }
    public SkinMenu(Layers layers) { this.layers=layers; library.open(); }
    private SkinLibrary activeLibrary() { return capes?capeLibrary:library; }
    public boolean focused() { return focused; }
    public HudMenu.Rect search() { return controls[SEARCH]; }
    public int selection() { return selection; }
    public void paste(String value) { if(focused) for(int cp:value.codePoints().toArray()) type(cp); }
    public boolean type(int cp) {
        if(!focused) return false;
        if(username.length()<16&&(cp>='a'&&cp<='z'||cp>='A'&&cp<='Z'||cp>='0'&&cp<='9'||cp=='_')) username+=(char)cp;
        return true;
    }
    public boolean backspace() {
        if(!focused) return false;
        if(!username.isEmpty()) username=username.substring(0,username.length()-1);
        return true;
    }
    public void focus() { if(!capes) { focused=true; selection=SEARCH; } }
    public boolean escape() {
        if(focused) { focused=false; return true; }
        if(!deleteId.isEmpty()) { deleteId=""; return true; }
        return false;
    }
    public void step(int delta) {
        focused=false;
        for(int n=0;n<controls.length;n++) {
            selection=Math.floorMod(selection+delta,controls.length);
            if(controls[selection]!=null) return;
        }
    }
    public boolean scroll(double amount) {
        if(amount==0) return false;
        firstRow=Math.max(0,Math.min(Math.max(0,activeLibrary().state().items().size()-1),firstRow+(amount<0?1:-1)));
        return true;
    }
    public int hit(double x,double y) {
        for(int i=0;i<controls.length;i++) if(controls[i]!=null&&controls[i].contains(x,y)) return i;
        return -1;
    }
    public boolean click(double x,double y) {
        int action=hit(x,y);
        if(action>=0) return activate(action);
        if(modelRect!=null&&modelRect.contains(x,y)) {
            focused=false; dragging=true; dragX=x; return true;
        }
        focused=false; return false;
    }
    public boolean drag(double x,double y) {
        if(!dragging) return false;
        yaw=(int)Math.round(yaw-(x-dragX)*1.5); dragX=x; return true;
    }
    public void release() { dragging=false; }
    public boolean activate(int action) {
        var library=activeLibrary();
        if(action==BACK) return false;
        if(action==SEARCH) { focus(); return true; }
        focused=false;
        if(action!=DELETE) deleteId="";
        if(action>=LAYER&&action<LAYER+6) { layers.set(layers.mask()^(1<<(action-LAYER))); return true; }
        switch(action) {
            case SKINS,CAPES -> {
                capes=action==CAPES; firstRow=0; yaw=capes?160:-20; dragging=false;
                if(capes&&!capeOpened) { capeOpened=true; capeLibrary.open(); }
            }
            case CAPE_VISIBLE -> layers.set(layers.mask()^64);
            case LOOKUP -> library.lookup(username);
            case IMPORT,CAPE_IMPORT -> library.chooseFile();
            case APPLY -> library.apply();
            case MODEL -> library.model();
            case LEFT -> yaw-=20;
            case RIGHT -> yaw+=20;
            case RESET -> { yaw=capes?160:-20; library.select(""); }
            case PREVIOUS -> { firstRow=0; library.page(-1); }
            case NEXT -> { firstRow=0; library.page(1); }
            case REFRESH -> library.load(library.state().offset());
            case GRID -> { grid=!grid; firstRow=0; }
            case EXPORT -> library.export();
            case DELETE -> {
                var skin=library.state().selectedSkin();
                if(skin!=null&&!skin.id().isEmpty()&&!skin.id().equals("__none__")) {
                    if(deleteId.equals(skin.id())) { library.delete(); deleteId=""; }
                    else deleteId=skin.id();
                }
            }
            default -> {
                int row=action-ROW;
                if(row<0||row>=library.state().items().size()) return false;
                library.select(library.state().items().get(row).id());
            }
        }
        return true;
    }
    public void dropped(List<Path> paths) { if(!paths.isEmpty()) activeLibrary().importPath(paths.get(0)); }
    public void render(ClientUi.Canvas c,int w,int h,int mx,int my) {
        Arrays.fill(controls,null);
        var library=activeLibrary();
        var liveCape=LiveCape.get();
        if(liveCape!=null&&seenCapeRevision!=liveCape.revision()) {
            seenCapeRevision=liveCape.revision();
            if(!liveCape.hidden()) layers.set(layers.mask()|64);
        }
        var state=library.state(); var chosen=state.selectedSkin();
        int pad=8,button=w<480?20:22,gap=3,sideW=Math.max(72,Math.min(208,w*22/100));
        int center=w/2,toolbarX=w-pad-(button+gap)*4+gap;
        int searchX=Math.max(sideW+18,w*33/100),searchY=w<480?35:8;
        int searchEnd=w<480?w-pad:Math.min(toolbarX-12,w*72/100);
        control(SKINS,pad,8,sideW/2-1,button);
        control(CAPES,pad+sideW/2+1,8,sideW/2-1,button);
        textButton(c,SKINS,c.translate("cubeonclient.skins.title"),sideW<100?.85f:1);
        textButton(c,CAPES,c.translate("cubeonclient.capes.title"),sideW<100?.85f:1);
        var tab=controls[capes?CAPES:SKINS];
        c.fill(tab.x()+2,tab.y()+tab.h()-2,tab.x()+tab.w()-2,tab.y()+tab.h()-1,WHITE);
        if(!capes) {
            control(SEARCH,searchX,searchY,Math.max(30,searchEnd-searchX-button-gap),button);
            control(LOOKUP,searchEnd-button,searchY,button,button);
            frame(c,controls[SEARCH],focused?0xD0212123:0xAF202022,focused?WHITE:RIM);
            var s=controls[SEARCH];
            String input=username.isEmpty()?c.translate("cubeonclient.skins.username"):username;
            ClientUi.left(c,ClientUi.fit(c,input+(focused?"_":""),s.w()-10),s.x()+5,s.y()+(button-9)/2,username.isEmpty()?DIM:WHITE);
        } else {
            ClientUi.left(c,ClientUi.fit(c,c.translate("cubeonclient.capes.choose"),searchEnd-searchX-button-8),searchX,searchY+(button-9)/2,DIM);
            control(CAPE_IMPORT,searchEnd-button,searchY,button,button);
        }
        control(BACK,toolbarX,8,button,button);
        if(!capes) control(MODEL,toolbarX+button+gap,8,button,button);
        control(REFRESH,toolbarX+2*(button+gap),8,button,button);
        control(RESET,toolbarX+3*(button+gap),8,button,button);

        int headerY=w<480?35:40,toolsY=w<480?59:headerY,listY=toolsY+27,listH=h-listY-pad;
        ClientUi.left(c,c.translate(capes?"cubeonclient.capes.title":"cubeonclient.skins.title"),pad,headerY,WHITE);
        String count=(state.offset()+Math.max(0,firstRow)) + " / " + state.total();
        ClientUi.left(c,count,pad,headerY+11,DIM);
        int small=Math.min(button,Math.max(16,(sideW-38)/3));
        int toolsX=pad+sideW-(small+gap)*3+gap;
        control(DELETE,toolsX,toolsY,small,small);
        control(GRID,toolsX+small+gap,toolsY,small,small);
        control(EXPORT,toolsX+2*(small+gap),toolsY,small,small);
        // The whole library is a drop target; only its empty/import area is clickable.
        c.fill(pad,listY,pad+sideW,listY+listH,0x392E3032);
        cornerBorder(c,pad,listY,sideW,listH);
        var uploads=capes?state.items():state.items().stream().filter(item->!item.id().isEmpty()).toList();
        int pagingY=listY+listH-23,available=pagingY-listY-4;
        if(uploads.isEmpty()) {
            control(IMPORT,pad+2,listY+2,sideW-4,listH-4);
            int cy=listY+listH/2-14;
            arrow(c,pad+sideW/2-6,cy-12,12);
            c.text(ClientUi.fit(c,c.translate(capes?"cubeonclient.capes.drop":"cubeonclient.skins.drop"),sideW-8),pad+sideW/2,cy+12,WHITE);
            c.text(ClientUi.fit(c,c.translate("cubeonclient.skins.click_import"),sideW-8),pad+sideW/2,cy+26,DIM);
        } else {
            int columns=grid?Math.max(1,(sideW-8)/38):1,rowH=grid?42:28;
            int rows=Math.max(1,(available-24)/rowH),visible=rows*columns;
            firstRow=Math.min(firstRow,Math.max(0,uploads.size()-visible));
            for(int j=0;j<visible&&firstRow+j<uploads.size();j++) {
                var skin=uploads.get(firstRow+j); int index=state.items().indexOf(skin);
                int cellW=(sideW-8)/columns,cx=pad+4+(j%columns)*cellW,cy=listY+4+(j/columns)*rowH;
                control(ROW+index,cx,cy,cellW-2,rowH-3);
                boolean active=skin.id().equals(state.selected());
                frame(c,controls[ROW+index],active?0xA0656568:0x48353538,active?WHITE:0x80636366);
                int size=grid?24:16;
                SkinPreview.face(c,skin,grid?cx+(cellW-size)/2:cx+4,cy+4,size);
                if(!grid) ClientUi.left(c,ClientUi.fit(c,skin.name(),cellW-26),cx+24,cy+9,WHITE);
                else c.text(ClientUi.fit(c,skin.name(),cellW-4),cx+cellW/2,cy+29,DIM);
            }
            control(IMPORT,pad+4,pagingY-22,sideW-8,20);
            if(state.total()>state.pageSize()) {
                control(PREVIOUS,pad+4,pagingY,20,20);
                control(NEXT,pad+sideW-24,pagingY,20,20);
                c.text((state.offset()/state.pageSize()+1)+" / "+Math.max(1,(state.total()+state.pageSize()-1)/state.pageSize()),
                        pad+sideW/2,pagingY+6,DIM);
            }
        }

        int nameY=Math.max(searchY+button+12,h*17/100),top=nameY+22;
        int confirmH=h<280?24:30,confirmY=h*80/100;
        int previewH=Math.max(48,confirmY-top-15),previewW=Math.min(180,Math.max(48,(center-(pad+sideW+button+gap+4))*2));
        modelRect=new HudMenu.Rect(center-previewW/2,top,previewW,previewH);
        c.textScaled(ClientUi.fit(c,library.playerName(),(int)(w*.35)),center,nameY,WHITE,h<280?1.2f:1.5f);
        int pedestalY=top+previewH-3;
        oval(c,center,pedestalY,Math.max(25,previewW/3),5,0xCDA0A0AC);
        oval(c,center,pedestalY,Math.max(23,previewW/3-2),3,0xC0272734);
        var body=capes?(this.library.state().applied()!=null?this.library.state().applied():capeLibrary.playerSkin()):chosen;
        var cape=capes?chosen:capeLibrary.state().applied();
        if(body!=null) preview.render(c,body,cape,modelRect.x(),top,previewW,previewH,yaw,layers.mask());
        int sideLeft=modelRect.x()-button-gap,sideRight=modelRect.x()+previewW+gap;
        for(int i=0;i<(capes?0:6);i++) {
            int cy=top+previewH/4+(i/2)*Math.max(button+gap,previewH/4);
            control(LAYER+i,i%2==0?sideLeft:sideRight,cy,button,button);
        }
        if(capes) {
            control(CAPE_VISIBLE,sideLeft,top+previewH/2,button,button);
            if(chosen!=null) c.text(ClientUi.fit(c,chosen.name(),previewW+button*2),center,confirmY-12,DIM);
        }
        int confirmW=Math.min(w*30/100,Math.max(80,w-sideW*2-32));
        control(APPLY,center-confirmW/2,confirmY,confirmW,confirmH);
        if(!dragging&&(lastX!=mx||lastY!=my)) { selection=hit(mx,my); lastX=mx; lastY=my; }
        for(int id:new int[]{BACK,MODEL,REFRESH,RESET,LOOKUP,DELETE,GRID,EXPORT,PREVIOUS,NEXT,CAPE_IMPORT}) iconButton(c,id,false);
        for(int i=0;i<(capes?0:6);i++) iconButton(c,LAYER+i,(layers.mask()&(1<<i))!=0);
        if(capes) iconButton(c,CAPE_VISIBLE,(layers.mask()&64)!=0);
        // Empty-library import uses the large transparent drop panel, not another dialog button.
        if(!uploads.isEmpty()) textButton(c,IMPORT,c.translate(capes?"cubeonclient.capes.import":"cubeonclient.skins.import"),1);
        textButton(c,APPLY,c.translate(state.busy()?"cubeonclient.skins.working":"cubeonclient.skins.confirm"),h<280?1.2f:1.8f);
        String status=deleteId.isEmpty()?state.status():c.translate(capes?"cubeonclient.capes.delete_confirm":"cubeonclient.skins.delete_confirm");
        if(status.isEmpty()&&!state.support()) status=c.translate("cubeonclient.skins.disabled");
        if(!status.isEmpty()) c.text(ClientUi.fit(c,status,w-pad*2),w/2,h-12,DIM);
        String tip=tooltip(c,selection,chosen);
        if(!tip.isEmpty()&&!dragging) {
            int tw=Math.min(w-16,c.width(tip)+12),tx=Math.max(8,Math.min(w-tw-8,mx-tw/2));
            int ty=Math.max(8,Math.min(h-26,my+17));
            c.fill(tx,ty,tx+tw,ty+18,0xF018181B);
            c.text(ClientUi.fit(c,tip,tw-8),tx+tw/2,ty+5,WHITE);
        }
    }
    private String tooltip(ClientUi.Canvas c,int action,SkinLibrary.Skin chosen) {
        if(action==CAPE_VISIBLE) return c.translate("cubeonclient.capes.visible")+" · "+c.translate((layers.mask()&64)!=0?"options.on":"options.off");
        if(action==CAPE_IMPORT) return c.translate("cubeonclient.capes.import");
        if(action>=LAYER&&action<LAYER+6) return c.translate("cubeonclient.skins."+PARTS[action-LAYER])
                +" · "+c.translate((layers.mask()&(1<<(action-LAYER)))!=0?"options.on":"options.off");
        if(action==MODEL) return c.translate("cubeonclient.skins.model")+": "+(chosen==null?"Auto":switch(chosen.model()) {
            case "slim"->"Alex (3 px)";case "classic"->"Steve (4 px)";default->"Auto";});
        String key=switch(action) {
            case BACK->"back";case RESET->"default";case LOOKUP->"find";case DELETE->"delete";
            case GRID->"view";case EXPORT->"export";case REFRESH->"refresh";
            default->"";
        };
        return key.isEmpty()?"":c.translate((capes&&action!=BACK&&action!=REFRESH&&action!=GRID?"cubeonclient.capes.":"cubeonclient.skins.")+key);
    }
    private void control(int id,int x,int y,int w,int h) { controls[id]=new HudMenu.Rect(x,y,w,h); }
    private static void frame(ClientUi.Canvas c,HudMenu.Rect r,int fill,int border) {
        c.fill(r.x(),r.y(),r.x()+r.w(),r.y()+r.h(),0xB0101012);
        c.fill(r.x()+1,r.y()+1,r.x()+r.w()-1,r.y()+r.h()-1,border);
        c.fill(r.x()+2,r.y()+2,r.x()+r.w()-2,r.y()+r.h()-2,fill);
        c.fill(r.x()+2,r.y()+r.h()-3,r.x()+r.w()-2,r.y()+r.h()-2,0x70303033);
    }
    private void textButton(ClientUi.Canvas c,int id,String label,float scale) {
        var r=controls[id]; if(r==null) return;
        frame(c,r,selection==id?0xD0606065:GREY,selection==id?WHITE:RIM);
        c.textScaled(ClientUi.fit(c,label,(int)((r.w()-12)/scale)),r.x()+r.w()/2,r.y()+(r.h()-(int)(9*scale))/2,WHITE,scale);
    }
    private void iconButton(ClientUi.Canvas c,int id,boolean on) {
        var r=controls[id]; if(r==null) return;
        frame(c,r,selection==id?0xD0606065:GREY,on?0xFFBABABE:selection==id?WHITE:RIM);
        int x=r.x()+r.w()/2-5,y=r.y()+r.h()/2-5,color=on||selection==id?WHITE:0xFFC5C5C9;
        switch(id) {
            case BACK -> { c.fill(x,y+4,x+10,y+6,color); c.fill(x,y+2,x+2,y+8,color); c.fill(x+2,y,x+4,y+2,color); c.fill(x+2,y+8,x+4,y+10,color); }
            case LOOKUP,CAPE_IMPORT -> {
                var skin=activeLibrary().state().applied();
                if(skin!=null) SkinPreview.face(c,skin,x,y+2,8);
                else c.fill(x,y+2,x+8,y+10,color);
                c.fill(x+7,y,x+12,y+2,color); c.fill(x+9,y-2,x+11,y+4,color);
            }
            case DELETE -> { c.fill(x,y+1,x+10,y+3,color); c.fill(x+2,y-1,x+8,y+1,color); c.fill(x+2,y+3,x+8,y+10,color); c.fill(x+3,y+4,x+4,y+8,0xFF39393B); c.fill(x+6,y+4,x+7,y+8,0xFF39393B); }
            case GRID -> { for(int i=0;i<4;i++) c.fill(x+(i%2)*6,y+(i/2)*6,x+(i%2)*6+4,y+(i/2)*6+4,color); }
            case EXPORT,NEXT,PREVIOUS -> { if(id==EXPORT) arrow(c,x,y,10); else c.text(id==NEXT?">":"<",r.x()+r.w()/2,r.y()+6,color); }
            case REFRESH -> { c.fill(x,y,x+9,y+2,color); c.fill(x,y,x+2,y+7,color); c.fill(x+8,y+3,x+10,y+10,color); c.fill(x+1,y+8,x+10,y+10,color); c.fill(x+6,y,x+10,y+4,color); }
            case CAPE_VISIBLE -> { c.fill(x+2,y,x+8,y+2,color); c.fill(x+1,y+2,x+9,y+10,color); if(!on) c.fill(x,y+9,x+10,y+10,0xFFAB5656); }
            case MODEL,RESET -> { c.fill(x+3,y,x+7,y+3,color); c.fill(x,y+4,x+10,y+6,color); c.fill(x+3,y+3,x+7,y+10,color); c.fill(x+2,y+8,x+4,y+12,color); c.fill(x+6,y+8,x+8,y+12,color); }
            default -> {
                int part=id-LAYER;
                if(part==0) { c.fill(x+1,y,x+9,y+8,color); c.fill(x+3,y+3,x+4,y+4,0xFF39393B); c.fill(x+6,y+3,x+7,y+4,0xFF39393B); }
                else if(part==1) { c.fill(x,y+1,x+10,y+9,color); c.fill(x+4,y+1,x+6,y+4,0xFF39393B); }
                else { c.fill(x+3,y,x+7,y+10,color); c.fill(x+2,y+1,x+3,y+9,color); c.fill(x+7,y+1,x+8,y+9,color); }
                if(!on) { c.fill(x,y+9,x+10,y+10,0xFFAB5656); }
            }
        }
    }
    private static void arrow(ClientUi.Canvas c,int x,int y,int size) {
        c.fill(x+size/2-1,y,x+size/2+1,y+size-2,WHITE);
        for(int i=0;i<3;i++) c.fill(x+size/2-i-1,y+size-4-i,x+size/2+i+1,y+size-3-i,WHITE);
        c.fill(x-2,y+size+1,x+size+2,y+size+3,WHITE);
    }
    private static void cornerBorder(ClientUi.Canvas c,int x,int y,int w,int h) {
        for(int dx:new int[]{0,1}) for(int dy:new int[]{0,1}) {
            int cx=x+dx*(w-1),cy=y+dy*(h-1);
            c.fill(dx==0?cx:cx-8,cy,dx==0?cx+9:cx+1,cy+1,0xAABABABE);
            c.fill(cx,dy==0?cy:cy-8,cx+1,dy==0?cy+9:cy+1,0xAABABABE);
        }
    }
    private static void oval(ClientUi.Canvas c,int cx,int cy,int rx,int ry,int color) {
        for(int y=-ry;y<=ry;y++) {
            int dx=(int)Math.round(rx*Math.sqrt(Math.max(0,1-(double)y*y/(ry*ry))));
            c.fill(cx-dx,cy+y,cx+dx+1,cy+y+1,color);
        }
    }
    @Override public void close() { library.close(); capeLibrary.close(); }
}
