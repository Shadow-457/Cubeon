#version 150
uniform sampler2D InSampler;
in vec2 texCoord;
out vec4 fragColor;
void main() {
    // Preserve raw world RGB even where vanilla sky attachment alpha is zero.
    fragColor = vec4(texture(InSampler, texCoord).rgb, 1.0);
}
