package com.cubeon.compat;

import java.net.URI;
import java.nio.charset.Charset;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

public final class HttpRequest {
    final URI uri;
    final Map<String, String> headers;
    final byte[] body;
    final Duration timeout;
    private HttpRequest(Builder b) {
        uri = b.uri; headers = new LinkedHashMap<String, String>(b.headers);
        body = b.body; timeout = b.timeout;
    }
    public static Builder newBuilder(URI uri) { return new Builder(uri); }
    public static final class Builder {
        private final URI uri;
        private final Map<String, String> headers = new LinkedHashMap<String, String>();
        private byte[] body;
        private Duration timeout = Duration.ofSeconds(2);
        private Builder(URI uri) { this.uri = uri; }
        public Builder header(String name, String value) {
            if (name.indexOf('\r') >= 0 || name.indexOf('\n') >= 0 || value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0)
                throw new IllegalArgumentException("Invalid HTTP header");
            headers.put(name, value); return this;
        }
        public Builder timeout(Duration value) { timeout = value; return this; }
        public Builder GET() { body = null; return this; }
        public Builder POST(byte[] value) { body = value.clone(); return this; }
        public HttpRequest build() { return new HttpRequest(this); }
    }
    public static final class BodyPublishers {
        public static byte[] ofString(String value, Charset charset) { return value.getBytes(charset); }
    }
}
