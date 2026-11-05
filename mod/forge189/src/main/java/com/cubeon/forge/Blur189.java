package com.cubeon.forge;
import com.cubeon.client.hud.*;
import net.minecraft.client.Minecraft;
import org.lwjgl.opengl.*;

/** Fixed exposure over this frame's color/depth. No history image or ghost accumulation. */
public final class Blur189 {
    private static int program,color,depth,width,height;
    private static boolean failed;
    private static Object world;
    private static final String VERTEX="#version 120\nvarying vec2 uv; void main(){ gl_Position=gl_Vertex; uv=gl_MultiTexCoord0.xy; }";
    private static final String FRAGMENT="#version 120\nuniform sampler2D image; uniform sampler2D depthImage; uniform vec2 motion; varying vec2 uv;\n"
        +"void main(){ vec4 total=vec4(0.0); float weights=0.0; float base=texture2D(depthImage,uv).r;"
        +"for(int i=0;i<9;i++){ float t=float(i)/8.0-0.5; vec2 at=clamp(uv+motion*t,vec2(0.0),vec2(1.0));"
        +"float z=texture2D(depthImage,at).r; float w=1.0-abs(t);"
        +"if(abs(z-base)<=max(0.00005,(1.0-base)*0.15)){total+=texture2D(image,at)*w; weights+=w;} }"
        +"gl_FragColor=weights>0.0?total/weights:texture2D(image,uv);}";
    private static int shader(int type,String source) {
        int s=GL20.glCreateShader(type); GL20.glShaderSource(s,source); GL20.glCompileShader(s);
        if(GL20.glGetShaderi(s,GL20.GL_COMPILE_STATUS)==0) {
            String error=GL20.glGetShaderInfoLog(s,2048); GL20.glDeleteShader(s); throw new IllegalStateException(error);
        }
        return s;
    }
    private static int texture(int format,int w,int h) {
        int id=GL11.glGenTextures(); GL11.glBindTexture(GL11.GL_TEXTURE_2D,id);
        GL11.glTexParameteri(GL11.GL_TEXTURE_2D,GL11.GL_TEXTURE_MIN_FILTER,GL11.GL_LINEAR);
        GL11.glTexParameteri(GL11.GL_TEXTURE_2D,GL11.GL_TEXTURE_MAG_FILTER,GL11.GL_LINEAR);
        GL11.glTexParameteri(GL11.GL_TEXTURE_2D,GL11.GL_TEXTURE_WRAP_S,GL12.GL_CLAMP_TO_EDGE);
        GL11.glTexParameteri(GL11.GL_TEXTURE_2D,GL11.GL_TEXTURE_WRAP_T,GL12.GL_CLAMP_TO_EDGE);
        GL11.glCopyTexImage2D(GL11.GL_TEXTURE_2D,0,format,0,0,w,h,0); return id;
    }
    private static void release() {
        if(color!=0) GL11.glDeleteTextures(color); if(depth!=0) GL11.glDeleteTextures(depth);
        if(program!=0) GL20.glDeleteProgram(program); program=color=depth=width=height=0;
        CameraBlur.INSTANCE.reset();
    }
    public static void draw() {
        Minecraft mc=Minecraft.getMinecraft(); CubeonHudConfig c=CubeonHudConfig.get();
        if(!c.cameraMotionBlur || mc.thePlayer==null || mc.theWorld==null || mc.currentScreen!=null || mc.gameSettings.anaglyph) {
            if(program!=0 || color!=0 || depth!=0) release();
            if(!c.cameraMotionBlur) failed=false;
            CameraBlur.INSTANCE.reset(); return;
        }
        if(world!=mc.theWorld) { release(); world=mc.theWorld; failed=false; }
        if(failed || !GLContext.getCapabilities().OpenGL20) return;
        double fov=mc.gameSettings.fovSetting;
        if(CubeonForge.held(CubeonForge.ZOOM)) fov/=c.zoomFactor;
        CameraBlur.INSTANCE.update(System.nanoTime(),RenderHooks.yaw(mc.thePlayer),RenderHooks.pitch(mc.thePlayer),fov,
                mc.displayWidth/(double)Math.max(1,mc.displayHeight),mc.theWorld,true,c.cameraBlurIntensity);
        if(!CameraBlur.INSTANCE.moving()) return;
        int active=GL11.glGetInteger(GL13.GL_ACTIVE_TEXTURE), previous=GL11.glGetInteger(GL20.GL_CURRENT_PROGRAM);
        GL11.glPushAttrib(GL11.GL_ENABLE_BIT|GL11.GL_COLOR_BUFFER_BIT|GL11.GL_DEPTH_BUFFER_BIT|GL11.GL_TEXTURE_BIT|GL11.GL_VIEWPORT_BIT);
        try {
            GL13.glActiveTexture(GL13.GL_TEXTURE0);
            if(program==0) {
                int v=0,f=0;
                try {
                    v=shader(GL20.GL_VERTEX_SHADER,VERTEX); f=shader(GL20.GL_FRAGMENT_SHADER,FRAGMENT);
                    program=GL20.glCreateProgram(); GL20.glAttachShader(program,v); GL20.glAttachShader(program,f); GL20.glLinkProgram(program);
                    if(GL20.glGetProgrami(program,GL20.GL_LINK_STATUS)==0) throw new IllegalStateException(GL20.glGetProgramInfoLog(program,2048));
                } finally { if(v!=0) GL20.glDeleteShader(v); if(f!=0) GL20.glDeleteShader(f); }
            }
            if(width!=mc.displayWidth || height!=mc.displayHeight) {
                if(color!=0) GL11.glDeleteTextures(color); if(depth!=0) GL11.glDeleteTextures(depth);
                width=mc.displayWidth; height=mc.displayHeight;
                color=texture(GL11.GL_RGBA8,width,height); depth=texture(GL14.GL_DEPTH_COMPONENT24,width,height);
            }
            GL11.glBindTexture(GL11.GL_TEXTURE_2D,color); GL11.glCopyTexSubImage2D(GL11.GL_TEXTURE_2D,0,0,0,0,0,width,height);
            GL13.glActiveTexture(GL13.GL_TEXTURE1); GL11.glBindTexture(GL11.GL_TEXTURE_2D,depth);
            GL11.glCopyTexSubImage2D(GL11.GL_TEXTURE_2D,0,0,0,0,0,width,height);
            GL13.glActiveTexture(GL13.GL_TEXTURE0); GL11.glBindTexture(GL11.GL_TEXTURE_2D,color);
            GL11.glDisable(GL11.GL_DEPTH_TEST); GL11.glDepthMask(false); GL11.glDisable(GL11.GL_BLEND); GL11.glDisable(GL11.GL_ALPHA_TEST); GL11.glDisable(GL11.GL_CULL_FACE);
            GL20.glUseProgram(program); GL20.glUniform1i(GL20.glGetUniformLocation(program,"image"),0);
            GL20.glUniform1i(GL20.glGetUniformLocation(program,"depthImage"),1);
            GL20.glUniform2f(GL20.glGetUniformLocation(program,"motion"),CameraBlur.INSTANCE.x(),CameraBlur.INSTANCE.y());
            GL11.glBegin(GL11.GL_QUADS);
            GL11.glTexCoord2f(0,0); GL11.glVertex2f(-1,-1); GL11.glTexCoord2f(1,0); GL11.glVertex2f(1,-1);
            GL11.glTexCoord2f(1,1); GL11.glVertex2f(1,1); GL11.glTexCoord2f(0,1); GL11.glVertex2f(-1,1); GL11.glEnd();
        } catch(RuntimeException error) {
            failed=true; release(); org.apache.logging.log4j.LogManager.getLogger("CubeonClient").warn("Camera blur unavailable",error);
        } finally {
            GL20.glUseProgram(previous); GL11.glPopAttrib(); GL13.glActiveTexture(active);
        }
    }
}
