#version 150
uniform sampler2D InSampler;
uniform sampler2D HistorySampler;
layout(std140) uniform CameraBlur { vec2 BlurVector; };
in vec2 texCoord;
out vec4 fragColor;
void main() {
    // Values >= 1 select Motion blur+; ordinary camera vectors stay below 0.12.
    if (BlurVector.x >= 1.0) {
        vec3 current = texture(InSampler, texCoord).rgb;
        float weight = clamp(BlurVector.x - 1.0, 0.0, 0.45);
        // First frames/cuts never read uninitialized or stale history.
        fragColor = vec4(weight <= 0.0 ? current : mix(current, texture(HistorySampler, texCoord).rgb, weight), 1.0);
        return;
    }
    vec2 halfTexel = 0.5 / vec2(textureSize(InSampler, 0));
    vec4 total = vec4(0.0);
    // Twelve samples across one fixed shutter exposure, using only this frame.
    for (int i = 0; i < 12; ++i) {
        float offset = (float(i) + 0.5) / 12.0 - 0.5;
        vec2 uv = clamp(texCoord + BlurVector * offset, halfTexel, vec2(1.0) - halfTexel);
        total += texture(InSampler, uv);
    }
    // World color is opaque even where the sky leaves attachment alpha at zero.
    fragColor = vec4(total.rgb / 12.0, 1.0);
}
