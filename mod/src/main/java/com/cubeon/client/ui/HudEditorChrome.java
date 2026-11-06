package com.cubeon.client.ui;

/** Floating toolbars and selection frame; native screens retain drag/scale/save ownership. */
public final class HudEditorChrome {
    private HudEditorChrome() { }
    public static boolean overlaps(int x, int y, int w, int h, int px, int py, int pw, int ph) {
        return x < px + pw && x + w > px && y < py + ph && y + h > py;
    }
    public static void peer(ClientUi.Canvas canvas, int width, int height, int x, int y, int w, int h,
                            int selectedX, int selectedY, int selectedW, int selectedH) {
        int color = overlaps(x,y,w,h,selectedX,selectedY,selectedW,selectedH)
                ? 0xD8FFC070 : 0x80939393;
        int left=Math.max(0,x-2),top=Math.max(0,y-2),right=Math.min(width,x+w+2),bottom=Math.min(height,y+h+2);
        if(right<=left||bottom<=top) return;
        canvas.fill(left,top,right,Math.min(bottom,top+1),color);
        canvas.fill(left,Math.max(top,bottom-1),right,bottom,color);
        canvas.fill(left,top,Math.min(right,left+1),bottom,color);
        canvas.fill(Math.max(left,right-1),top,right,bottom,color);
    }
    public static boolean done(int width, int height, double x, double y) {
        int panelWidth = Math.min(340, width - 24), left = (width - panelWidth) / 2;
        return x >= left + panelWidth - 80 && x < left + panelWidth - 8 && y >= height - 40 && y < height - 16;
    }
    public static void render(ClientUi.Canvas canvas, int width, int height, String title,
                              int mouseX, int mouseY, int x, int y, int w, int h, boolean dragging) {
        int panelWidth = Math.min(340, width - 24), left = (width - panelWidth) / 2;
        MenuUi.panel(canvas, left, 12, panelWidth, 38, 10, MenuUi.SURFACE, MenuUi.BORDER_HI, 1);
        MenuUi.mark(canvas, left + 10, 22, 1);
        ClientUi.left(canvas, canvas.translate("cubeonclient.hud.editor"), left + 36, 20, MenuUi.TEXT);
        ClientUi.left(canvas, ClientUi.fit(canvas, title, panelWidth - 48), left + 36, 33, MenuUi.DIM);
        MenuUi.panel(canvas, left, height - 46, panelWidth, 36, 10, MenuUi.SURFACE, MenuUi.BORDER_HI, 1);
        ClientUi.left(canvas, ClientUi.fit(canvas, canvas.translate("cubeonclient.hud.drag_hint"), panelWidth - 104),
                left + 12, height - 32, MenuUi.DIM);
        MenuUi.button(canvas, left + panelWidth - 80, height - 40, 72, 24,
                canvas.translate("cubeonclient.emotes.done"), done(width, height, mouseX, mouseY) ? 1 : 0, true, 1);
        int color = dragging ? MenuUi.ACCENT_HI : MenuUi.ACCENT;
        // Draw the frame inside the screen even for widgets anchored flush to an edge.
        int x0 = Math.max(0, x - 3), y0 = Math.max(0, y - 3);
        int x1 = Math.min(width, x + w + 3), y1 = Math.min(height, y + h + 3);
        canvas.fill(x0, y0, x1, Math.min(y1, y0 + 1), color);
        canvas.fill(x0, Math.max(y0, y1 - 1), x1, y1, color);
        canvas.fill(x0, y0, Math.min(x1, x0 + 1), y1, color);
        canvas.fill(Math.max(x0, x1 - 1), y0, x1, y1, color);
        for (int hx : new int[]{x0, Math.max(x0, x1 - 3)})
            for (int hy : new int[]{y0, Math.max(y0, y1 - 3)})
                canvas.fill(hx, hy, Math.min(x1, hx + 3), Math.min(y1, hy + 3), color);
    }
}
