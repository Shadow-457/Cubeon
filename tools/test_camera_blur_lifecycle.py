"""Exercise production native adapters against resource-counting renderer doubles.

Gradle builds validate real API types; these checks cover the optional effect's
allocation, copy/draw ordering, reset scheduling and failure behavior.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

MAIN = Path(__file__).resolve().parents[1] / "mod/src/main"


def put(folder, name, body):
    package, _, simple = name.rpartition(".")
    path = folder / (name.replace(".", "/") + ".java")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"package {package};\n" + body.replace("CLASS", simple))


def fixtures(folder, era):
    base = "com.mojang.renderpearl.api" if era == "26.3" else "com.mojang.blaze3d"
    mojang = era.startswith("26")
    types = ["textures.FilterMode", "textures.AddressMode", "textures.TextureFormat",
             "platform.DepthTestFunction", "shaders.UniformType", "pipeline.UniformType"]
    for name in types:
        put(folder, base + "." + name, "public enum CLASS { LINEAR, CLAMP_TO_EDGE, NO_DEPTH_TEST, VEC2, UNIFORM_BUFFER, COMBINED_IMAGE_SAMPLER }")
    put(folder, "net.minecraft.client.gl.UniformType", "public enum CLASS { VEC2, UNIFORM_BUFFER }")
    put(folder, "org.slf4j.Logger", "public interface CLASS { default void warn(String s, Throwable t) {} }")
    put(folder, "org.slf4j.LoggerFactory", "public class CLASS { public static Logger getLogger(String s) { return new Logger() {}; } }")
    put(folder, "com.cubeon.client.hud.CubeonHudConfig", "public class CLASS { public boolean cameraMotionBlur; public float cameraBlurIntensity=1f; private static final CLASS C=new CLASS(); public static CLASS get() {return C;} }")
    put(folder, "test.Events", """public class CLASS {
        public static int live, allocations, copies, draws, attempts, submits, pipelines;
        public static boolean failAllocation, failDraw, copied;
        public static void allocate() { attempts++; if(failAllocation) throw new IllegalStateException("Unavailable renderer"); live++; allocations++; }
        public static void copy(Object a,Object b) { if(a==b) throw new AssertionError("Feedback loop"); copies++; copied=true; }
        public static void draw() { if(!copied) throw new AssertionError("Scene must be copied before drawing"); copied=false; if(failDraw) throw new IllegalStateException("Shader unavailable"); draws++; }
    }""")
    put(folder, "test.Resource", """public class CLASS implements AutoCloseable {
        private boolean closed, owned;
        public CLASS() { this(true); }
        public CLASS(boolean owned) { this.owned=owned; if(owned) Events.allocate(); }
        public void close() { if(owned && !closed) { Events.live--; closed=true; } }
    }""")
    put(folder, base + ".textures.GpuTexture", """public class CLASS extends test.Resource {
        public static final int USAGE_COPY_DST=1,USAGE_TEXTURE_BINDING=2;
        public CLASS() {super();} public CLASS(boolean owned) {super(owned);}
        public Object getFormat(){return new Object();}
        public void setTextureFilter(Object mode,boolean mip){} public void setAddressMode(Object mode){}
    }""")
    put(folder, base + ".textures.GpuTextureView", "public class CLASS extends test.Resource {}")
    put(folder, base + ".buffers.GpuBuffer", "public class CLASS extends test.Resource { public static final int USAGE_UNIFORM=1,USAGE_COPY_DST=2; public Object slice(){return this;} }")
    put(folder, "com.mojang.blaze3d.vertex.VertexFormat", """public class CLASS {
        public enum Mode { TRIANGLES } public enum DrawMode { TRIANGLES }
        public static CLASS builder(){return new CLASS();} public CLASS build(){return this;}
    }""")
    put(folder, base + ".pipeline.RenderPipeline", """public class CLASS {
        public static Builder builder(){return new Builder();}
        public static class Builder {
            private void identifier(Object o){if(o instanceof String && ((String)o).contains(":"))throw new IllegalArgumentException("String overload assumes the Minecraft namespace");}
            public Builder withLocation(Object o){identifier(o);return this;} public Builder withVertexShader(Object o){identifier(o);return this;}
            public Builder withFragmentShader(Object o){identifier(o);return this;} public Builder withCull(boolean o){return this;}
            public Builder withSampler(Object o){return this;} public Builder withUniform(String s,Object o){return this;}
            public Builder withDepthTestFunction(Object o){return this;} public Builder withDepthWrite(boolean o){return this;}
            public Builder withoutBlend(){return this;} public Builder withVertexFormat(Object a,Object b){return this;}
            public Builder withBindGroupLayout(Object o){return this;} public Builder withPrimitiveTopology(Object o){return this;}
            public Builder withColorTargetState(Object o){return this;} public Builder withDepthStencilState(Object o){return this;}
            public CLASS build(){test.Events.pipelines++; return new CLASS();}
        }
    }""")
    put(folder, base + ".pipeline.BindGroupLayout", """public class CLASS {
        public static CLASS builder(){return new CLASS();} public CLASS withSampler(String s){return this;}
        public CLASS withUniform(String s,Object o){return this;} public CLASS build(){return this;}
    }""")
    put(folder, base + ".pipeline.ColorTargetState", "public class CLASS { public static final CLASS DEFAULT=new CLASS(); }")
    put(folder, base + ".pipeline.PrimitiveTopology", "public enum CLASS { TRIANGLES }")
    put(folder, "com.mojang.blaze3d.PrimitiveTopology", "public enum CLASS { TRIANGLES }")
    put(folder, "com.mojang.blaze3d.systems.RenderSystem", """
    import BASE.textures.*; import BASE.buffers.*;
    public class CLASS {
        public static Device getDevice(){return new Device();} public static Object getCompiledPipeline(Object p){return p;}
        public static Samplers getSamplerCache(){return new Samplers();}
        public static class Samplers { public Object get(Object f){return f;} public Object getClampToEdge(Object f){return f;} }
        public static class Device {
            public GpuTexture createTexture(String label,Object... a){return new GpuTexture();}
            public GpuTextureView createTextureView(GpuTexture t){return new GpuTextureView();}
            public GpuBuffer createBuffer(java.util.function.Supplier<String> label,int flags,int size){return new GpuBuffer();}
            public Encoder createCommandEncoder(){return new Encoder();}
        }
        public static class Encoder {
            public void copyTextureToTexture(Object a,Object b,int... area){test.Events.copy(a,b);}
            public void writeToBuffer(Object b,java.nio.ByteBuffer data){if(data.remaining()!=16)throw new AssertionError("UBO size");}
            public Pass createRenderPass(Object target,Object clear){return new Pass();}
            public Pass createRenderPass(java.util.function.Supplier<String> label,Object target,Object clear){return new Pass();}
            public void submit(){test.Events.submits++;}
        }
        public static class Pass implements AutoCloseable {
            public void setPipeline(Object p){} public void bindSampler(String s,Object t){}
            public void bindTexture(String s,Object t,Object sampler){} public void setUniform(String s,Object b){}
            public void setUniform(String s,Object t,Object sampler){} public void setUniform(String s,float x,float y){}
            public void draw(int... range){test.Events.draw();} public void close(){}
        }
    }
    """.replace("BASE", base))
    framebuffer = "com.mojang.blaze3d.pipeline.RenderTarget" if mojang else "net.minecraft.client.gl.Framebuffer"
    put(folder, framebuffer, """import BASE.textures.*;
    public class CLASS {
        public int width=1280,height=720,textureWidth=1280,textureHeight=720;
        private GpuTexture color=new GpuTexture(false);
        public GpuTexture getColorAttachment(){return color;} public GpuTexture getColorTexture(){return color;}
        public GpuTextureView getColorAttachmentView(){return null;} public GpuTextureView getColorTextureView(){return null;}
        public void beginWrite(boolean viewport){}
    }""".replace("BASE", base))
    client = "net.minecraft.client.Minecraft" if mojang else "net.minecraft.client.MinecraftClient"
    camera = "net.minecraft.client.Camera" if mojang else "net.minecraft.client.render.Camera"
    renderer = "net.minecraft.client.renderer.GameRenderer" if mojang else "net.minecraft.client.render.GameRenderer"
    put(folder, client, """import FRAMEBUFFER;
    public class CLASS {
        private static final CLASS C=new CLASS(); public static CLASS getInstance(){return C;}
        public Object world=new Object(),level=world,currentScreen,screen;
        public Gui gui=new Gui(); public class Gui { public Object screen(){return CLASS.this.screen;} }
        private final Object resources=new Object(); public Object getResourceManager(){return resources;}
        public Object getTextureManager(){return resources;}
        public net.minecraft.client.gl.ShaderLoader getShaderLoader(){return new net.minecraft.client.gl.ShaderLoader();}
        public final FB frame=new FB(); public FB getFramebuffer(){return frame;} public FB getMainRenderTarget(){return frame;}
    }""".replace("FRAMEBUFFER", framebuffer).replace("FB", framebuffer.split(".")[-1]))
    put(folder, camera, """public class CLASS {
        public float yaw,pitch; public float getYaw(){return yaw;} public float getPitch(){return pitch;}
        public float yRot(){return yaw;} public float xRot(){return pitch;} public float getFov(){return 70;}
    }""")
    put(folder, renderer, """import CAMERA; import CLIENT; import FRAMEBUFFER;
    public class CLASS {
        public final CAM camera=new CAM(); public CAM getCamera(){return camera;} public CAM getMainCamera(){return camera;} public CAM mainCamera(){return camera;}
        public FB mainRenderTarget(){return CLI.getInstance().frame;}
    }""".replace("CAMERA", camera).replace("CLIENT", client).replace("FRAMEBUFFER", framebuffer)
        .replace("CAM", camera.split(".")[-1]).replace("CLI", client.split(".")[-1]).replace("FB", framebuffer.split(".")[-1]))
    put(folder, "net.minecraft.util.Identifier", "public class CLASS {public static CLASS tryParse(String s){return new CLASS();}}")
    put(folder, "net.minecraft.resources.Identifier", "public class CLASS {public static CLASS parse(String s){return new CLASS();}}")
    put(folder, "com.cubeon.client.hud.blur.mixin.CameraBlurPasses", "public interface CLASS {java.util.List<net.minecraft.client.gl.PostEffectPass> cubeon$passes();}")
    put(folder, "net.minecraft.client.gl.PostEffectPass", """public class CLASS {
        public CLASS getProgram(){return this;} public CLASS getUniform(String s){return this;}
        public CLASS getUniformByName(String s){return this;} public void set(float x,float y){}
    }""")
    put(folder, "net.minecraft.client.gl.PostEffectProcessor", """public class CLASS extends test.Resource implements com.cubeon.client.hud.blur.mixin.CameraBlurPasses {
        public static final Object MAIN=new Object();
        public CLASS(){super(false);} public CLASS(Object a,Object b,Object c,Object d){super();}
        public java.util.List<PostEffectPass> cubeon$passes(){return java.util.List.of(new PostEffectPass());}
        public void setupDimensions(int x,int y){}
        public void render(float delta){test.Events.copy(MAIN,new Object());test.Events.draw();}
        public void render(Object main,Object pool){test.Events.copy(main,new Object());test.Events.draw();}
    }""")
    put(folder, "net.minecraft.client.gl.ShaderLoader", "public class CLASS { public PostEffectProcessor loadPostEffect(Object id,Object targets){return new PostEffectProcessor();} }")
    put(folder, "net.minecraft.client.util.Pool", "public class CLASS extends test.Resource {public CLASS(int lifespan){} public void decrementLifespan(){} }")
    put(folder, "test.Lifecycle", """import CLIENT; import RENDERER;
    import com.cubeon.client.hud.CameraBlur;
    import com.cubeon.client.hud.CubeonHudConfig;
    import com.cubeon.client.hud.blur.CameraBlurRenderer;
    public class CLASS {
        static CLI client=CLI.getInstance(); static REN renderer=new REN();
        static void require(boolean good,String why){if(!good)throw new AssertionError(why);}
        static void frame(){CameraBlurRenderer.beginFrame();CameraBlurRenderer.render(renderer);}
        static void turn()throws Exception {Thread.sleep(10);renderer.camera.yaw+=2;frame();}
        static void world(){client.world=new Object();client.level=client.world;frame();}
        public static void main(String[] args)throws Exception {
            frame();turn();require(Events.allocations==0,"OFF never allocates or draws");
            CubeonHudConfig.get().cameraMotionBlur=true;frame();turn();
            require(Events.draws==1 && Events.copies==1 && Events.live>0,"ON copies current scene before the pass");
            int resources=Events.live, allocations=Events.allocations, draws=Events.draws;
            Thread.sleep(16);frame();require(Events.draws==draws,"Idle camera runs no blur pass after the input sampling window");
            turn();require(Events.allocations==allocations && Events.live==resources,"Frames reuse GPU resources");
            client.frame.width=client.frame.textureWidth=1920;client.frame.height=client.frame.textureHeight=1080;
            turn();require(Events.live==resources && Events.allocations>allocations,"Resize replaces resources without leaking");
            CameraBlurRenderer.reset();require(Events.live==resources,"Reload/settings requests defer GPU cleanup");
            frame();require(Events.live==0 && !CameraBlur.INSTANCE.moving(),"Next render cleans and clears exposure");
            turn();world();require(Events.live==0,"Changing worlds frees the scene resources");
            turn();client.screen=client.currentScreen=new Object();frame();require(Events.live==0,"Menus remain sharp and free resources");
            client.screen=client.currentScreen=null;frame();turn();
            CubeonHudConfig.get().cameraMotionBlur=false;frame();require(Events.live==0,"Turning OFF frees all resources");
            CubeonHudConfig.get().cameraMotionBlur=true;frame();Events.failAllocation=true;turn();
            int attempts=Events.attempts;turn();require(Events.attempts==attempts && Events.live==0,"Allocation failure disables retries during gameplay");
            Events.failAllocation=false;CameraBlurRenderer.reset();frame();Events.failDraw=true;turn();
            require(Events.live==0,"Failed draw cleans partially initialized resources");
            Events.failDraw=false;CameraBlurRenderer.reset();frame();turn();require(Events.live>0,"Explicit reset can recover the optional effect");
            CameraBlurRenderer.shutdown();CameraBlurRenderer.shutdown();require(Events.live==0,"Shutdown is idempotent");
            require(Events.pipelines<=1,"Pipeline descriptors must not accumulate across resize/toggles");
            System.out.println("ERA: off/idle, resource reuse, resize, world/menu/toggle/reload/close, copy ordering and failure recovery passed");
        }
    }""".replace("CLIENT", client).replace("RENDERER", renderer)
        .replace("CLI", client.split(".")[-1]).replace("REN", renderer.split(".")[-1]).replace("ERA", era))


class LifecycleTests(unittest.TestCase):
    def test_native_gpu_adapters(self):
        for era in ["legacy", "post", "gpu5", "gpu6", "gpu9", "26.1", "26.2", "26.3"]:
            with self.subTest(era=era), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                fixtures(folder, era)
                sources = list(folder.rglob("*.java")) + [
                    MAIN / "java/com/cubeon/client/hud/CameraBlur.java",
                    MAIN / f"java-overlay-camera-blur-{era}/com/cubeon/client/hud/blur/CameraBlurRenderer.java"]
                result = subprocess.run(["javac", "--release", "17", "-d", directory] + [str(p) for p in sources],
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run(["java", "-cp", directory, "test.Lifecycle"], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
