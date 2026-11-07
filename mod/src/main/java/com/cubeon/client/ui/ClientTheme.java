package com.cubeon.client.ui;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.file.*;
import java.util.Arrays;
import java.util.Properties;

/** Instance-local menu colors. No launcher, world, HUD or renderer settings are changed. */
public final class ClientTheme {
    public static final String[] NAMES = {"Default", "Spring", "Summer", "Autumn", "Winter", "Custom"};
    public static final String[] ROLES = {"Accent", "Background", "Cards", "Border", "Text", "Muted text"};
    // Accent, background, cards, border, text and muted text; all colors remain opaque.
    private static final int[][] PRESETS = {
        {0x83C13D,0x12161B,0x1A2027,0x303943,0xE6EDF3,0xA8B3C0},
        {0xE7A4C5,0x171B19,0x232D27,0x425C4A,0xF1F5EA,0xB5C7B7},
        {0xF5CE68,0x111E24,0x19313B,0x355561,0xF7F2DA,0xA9CAD2},
        {0xEAA060,0x211916,0x30231D,0x634535,0xF5EADD,0xC9B4A2},
        {0x9BCDF3,0x141B29,0x202C40,0x3D506D,0xEDF5FF,0xAFBFD5}
    };
    private static int selected;
    private static int[] custom=PRESETS[0].clone();
    private static Path file;
    private ClientTheme() {}
    public static int selected() { return selected; }
    public static int[] colors() { return (selected==5?custom:PRESETS[selected]).clone(); }
    public static int[] preset(int index) { return (index==5?custom:PRESETS[index]).clone(); }
    public static String hex(int color) { return String.format(java.util.Locale.ROOT,"%06X",color&0xFFFFFF); }
    public static boolean validHex(String value) { return value!=null && value.matches("[0-9a-fA-F]{6}"); }
    public static void load(Path target) {
        if(target.equals(file)) return;
        file=target; selected=0; custom=PRESETS[0].clone();
        try {
            if(!Files.isRegularFile(file) || Files.size(file)>4096) return;
            Properties values=new Properties();
            try(Reader reader=Files.newBufferedReader(file)) { values.load(reader); }
            int index=Integer.parseInt(values.getProperty("theme","0"));
            if(index>=0 && index<NAMES.length) selected=index;
            for(int i=0;i<custom.length;i++) {
                String value=values.getProperty("color."+i);
                if(validHex(value)) custom[i]=Integer.parseInt(value,16);
            }
        } catch(IOException | IllegalArgumentException ignored) { selected=0; custom=PRESETS[0].clone(); }
    }
    /** Persist first: failures leave the active theme and previous file intact. */
    public static boolean apply(int index,int[] draft) {
        if(index<0 || index>=NAMES.length || (index==5 && (draft==null || draft.length!=6))) return false;
        int[] next=index==5?Arrays.stream(draft).map(c->c&0xFFFFFF).toArray():custom.clone();
        Path temp=null;
        try {
            if(file!=null) {
                Files.createDirectories(file.getParent());
                temp=Files.createTempFile(file.getParent(),"cubeon-theme-",".tmp");
                Properties values=new Properties(); values.setProperty("theme",Integer.toString(index));
                for(int i=0;i<next.length;i++) values.setProperty("color."+i,hex(next[i]));
                try(Writer writer=Files.newBufferedWriter(temp)) { values.store(writer,"Cubeon in-game menu theme"); }
                try { Files.move(temp,file,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING); }
                catch(AtomicMoveNotSupportedException ignored) { Files.move(temp,file,StandardCopyOption.REPLACE_EXISTING); }
            }
            selected=index; custom=next; return true;
        } catch(IOException | SecurityException ignored) { return false; }
        finally { if(temp!=null) try { Files.deleteIfExists(temp); } catch(IOException ignored) {} }
    }
}
