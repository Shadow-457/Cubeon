#version 150
uniform sampler2D InSampler;
layout(std140) uniform CameraBlur { vec2 BlurVector; };
in vec2 texCoord;
out vec4 fragColor;
void main() {
    vec2 halfTexel = 0.5 / vec2(textureSize(InSampler, 0));
    vec4 total = vec4(0.0);
    // Twelve samples across one fixed shutter exposure, using only this frame.
    for (int i = 0; i < 12; ++i) {
        float offset = (float(i) + 0.5) / 12.0 - 0.5;
        vec2 uv = clamp(texCoord + BlurVector * offset, halfTexel, vec2(1.0) - halfTexel);
        total += texture(InSampler, uv);
    }
    fragColor = total / 12.0;
}
