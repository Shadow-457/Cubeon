"""Linux EGL check of production blur shaders, with pixel readback (PyOpenGL required)."""
import os
os.environ["PYOPENGL_PLATFORM"] = "egl"
os.environ.setdefault("EGL_PLATFORM", "surfaceless")

from ctypes import c_int, byref
from pathlib import Path
from OpenGL import EGL, GL
from OpenGL.GL.shaders import compileShader, compileProgram

ROOT = Path(__file__).resolve().parents[1] / "mod/src/main"
display = EGL.eglGetDisplay(EGL.EGL_DEFAULT_DISPLAY)
major, minor = c_int(), c_int()
if not EGL.eglInitialize(display, byref(major), byref(minor)):
    raise RuntimeError("EGL display initialization failed")
EGL.eglBindAPI(EGL.EGL_OPENGL_API)
attributes = (c_int * 13)(EGL.EGL_SURFACE_TYPE, EGL.EGL_PBUFFER_BIT,
                         EGL.EGL_RENDERABLE_TYPE, EGL.EGL_OPENGL_BIT,
                         EGL.EGL_RED_SIZE, 8, EGL.EGL_GREEN_SIZE, 8,
                         EGL.EGL_BLUE_SIZE, 8, EGL.EGL_ALPHA_SIZE, 8, EGL.EGL_NONE)
config = EGL.EGLConfig()
count = c_int()
EGL.eglChooseConfig(display, attributes, byref(config), 1, byref(count))
if not count.value:
    raise RuntimeError("EGL OpenGL config missing")
pbuffer_attributes = (c_int * 5)(EGL.EGL_WIDTH, 128, EGL.EGL_HEIGHT, 64, EGL.EGL_NONE)
surface = EGL.eglCreatePbufferSurface(display, config, pbuffer_attributes)
context = EGL.eglCreateContext(display, config, EGL.EGL_NO_CONTEXT, None)
EGL.eglMakeCurrent(display, surface, surface, context)

width, height = 128, 64
print("Native shader test:", GL.glGetString(GL.GL_RENDERER).decode(), GL.glGetString(GL.GL_VERSION).decode())
texture = GL.glGenTextures(1)
GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
vao = GL.glGenVertexArrays(1)
GL.glBindVertexArray(vao)
GL.glDisable(GL.GL_DEPTH_TEST)
GL.glDisable(GL.GL_BLEND)
GL.glViewport(0, 0, width, height)

vertex = """#version 330
out vec2 texCoord;
void main() {
 vec2 uv = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
 texCoord = uv; gl_Position = vec4(uv * 2.0 - 1.0, 0.0, 1.0);
}
"""
pixels = bytes(channel for y in range(height) for x in range(width)
               for channel in ((255 if (x // 8) % 2 else 0), y * 4, 100, 255))

def upload(data):
    GL.glActiveTexture(GL.GL_TEXTURE0)
    GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, data)


history = GL.glGenTextures(1)
GL.glActiveTexture(GL.GL_TEXTURE1)
GL.glBindTexture(GL.GL_TEXTURE_2D, history)
GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, bytes((200, 40, 60, 0)) * (width * height))

for fragment in sorted(ROOT.glob("resources-overlay-camera-blur-*/**/*.fsh")):
    resource = next(p for p in fragment.parents if p.name.startswith("resources-overlay-camera-blur-"))
    plus_only = "motion_plus" in fragment.stem
    scene_only = "motion_scene" in fragment.stem
    source = fragment.read_text()
    # RenderPearl translates its native vertex intrinsic for its backend.
    # All actual fragment sources are compiled unchanged, including 26.3.
    vertices = list(resource.rglob("*.vsh"))
    vertex_source = vertices[0].read_text().replace("gl_VertexIndex", "gl_VertexID") if vertices else vertex
    program = compileProgram(compileShader(vertex_source, GL.GL_VERTEX_SHADER), compileShader(source, GL.GL_FRAGMENT_SHADER))
    GL.glUseProgram(program)
    sampler = "DiffuseSampler" if "DiffuseSampler" in source else "InSampler"
    GL.glUniform1i(GL.glGetUniformLocation(program, sampler), 0)
    GL.glUniform1i(GL.glGetUniformLocation(program, "HistorySampler"), 1)
    ubo = None
    if "layout(std140)" in source:
        ubo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_UNIFORM_BUFFER, ubo)
        GL.glBufferData(GL.GL_UNIFORM_BUFFER, 16, None, GL.GL_DYNAMIC_DRAW)
        GL.glUniformBlockBinding(program, GL.glGetUniformBlockIndex(program, "CameraBlur"), 0)
        GL.glBindBufferBase(GL.GL_UNIFORM_BUFFER, 0, ubo)

    def draw(x, y):
        if ubo:
            import struct
            GL.glBindBuffer(GL.GL_UNIFORM_BUFFER, ubo)
            GL.glBufferSubData(GL.GL_UNIFORM_BUFFER, 0, 16, struct.pack("4f", x, y, 0, 0))
        else:
            GL.glUniform2f(GL.glGetUniformLocation(program, "BlurVector"), x, y)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        return GL.glReadPixels(0, 0, width, height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)

    if scene_only:
        upload(pixels)
        assert draw(0, 0) == pixels, "Raw history preserves the current scene exactly"
        upload(bytes((37, 126, 220, 0)) * (width * height))
        assert draw(0, 0) == bytes((37, 126, 220, 255)) * (width * height), "Raw history preserves zero-alpha sky RGB"
    if not plus_only and not scene_only:
        upload(pixels)
        sharp = draw(0, 0)
        assert sharp == pixels, f"{resource.name}: zero-vector must preserve the scene exactly"
        blurred = draw(.06, 0)
        assert blurred != sharp, f"{resource.name}: moving camera must visibly blur"
        assert all(blurred[i] == pixels[i] for i in range(1, len(pixels), 4)), "Horizontal blur must not smear vertical detail"
        assert all(blurred[i] == 255 for i in range(3, len(pixels), 4)), "Opaque scene must stay opaque"
        for color in [(0, 0, 0, 255), (37, 126, 220, 255)]:
            solid = bytes(color) * (width * height)
            upload(solid)
            result = draw(.06, .025)
            assert all(abs(a-b) <= 1 for a, b in zip(result, solid)), "No prior-frame ghost or dark borders allowed"
        # Vanilla's lower sky can have RGB sky color with alpha zero. The legacy
        # second pass uses alpha blending after clearing main: zero alpha made it black.
        transparent_sky = bytes((37, 126, 220, 0)) * (width * height)
        upload(transparent_sky)
        result = draw(.06, .025)
        assert all(abs(result[i + c] - (37, 126, 220, 255)[c]) <= 1
                   for i in range(0, len(result), 4) for c in range(4)), "Sky RGB must survive zero attachment alpha"
    if plus_only or "HistorySampler" in source:
        upload(bytes((20, 100, 180, 0)) * (width * height))
        for weight in (0, .3, .8):
            result = draw(weight if plus_only else 1 + weight, 0)
            expected_weight = min(.45, weight)
            expected = (round(20 * (1-expected_weight) + 200 * expected_weight), round(100 * (1-expected_weight) + 40 * expected_weight), round(180 * (1-expected_weight) + 60 * expected_weight), 255)
            assert all(abs(result[i+c] - expected[c]) <= 1 for i in range(0, len(result), 4) for c in range(4)), f"{fragment}: temporal seed/blend preserves RGB and opaque sky"
    assert GL.glGetError() == GL.GL_NO_ERROR
    if ubo:
        GL.glDeleteBuffers(1, [ubo])
    GL.glDeleteProgram(program)
    print(resource.name, fragment.stem, "compiled; scene pixels and temporal blend checks passed")

GL.glDeleteTextures([texture, history])
GL.glDeleteVertexArrays(1, [vao])
EGL.eglMakeCurrent(display, EGL.EGL_NO_SURFACE, EGL.EGL_NO_SURFACE, EGL.EGL_NO_CONTEXT)
EGL.eglDestroyContext(display, context)
EGL.eglDestroySurface(display, surface)
EGL.eglTerminate(display)
