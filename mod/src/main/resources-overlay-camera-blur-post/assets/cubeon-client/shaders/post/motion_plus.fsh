#version 150
uniform sampler2D InSampler;
uniform sampler2D HistorySampler;
uniform vec2 BlurVector;
in vec2 texCoord;
out vec4 fragColor;
void main() {
    vec3 current = texture(InSampler, texCoord).rgb;
    float weight = clamp(BlurVector.x, 0.0, 0.45);
    fragColor = vec4(weight <= 0.0 ? current : mix(current, texture(HistorySampler, texCoord).rgb, weight), 1.0);
}
